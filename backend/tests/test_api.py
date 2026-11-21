import uuid

import pytest


def sid():
    return f"s-{uuid.uuid4().hex[:8]}"


def uniq(prefix="q"):
    return f"{prefix} {uuid.uuid4().hex}"


def chat(client, session_id, message, headers=None, **extra):
    return client.post("/chat", json={"session_id": session_id, "message": message, **extra}, headers=headers or {})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_chat_contract(client):
    s = sid()
    r = chat(client, s, uniq())
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == s and body["reply"]
    md = body["metadata"]
    assert md["resolution_source"] == "LIVE_INFERENCE"
    assert md["key_id"] == "key_1" and md["fallback_attempts"] == 0
    assert isinstance(md["latency_ms"], int) and md["input_tokens"] > 0 and md["output_tokens"] > 0
    assert "test-key" not in r.text


def test_cache_hit_across_sessions(client):
    msg = uniq()
    first = chat(client, sid(), msg).json()
    second = chat(client, sid(), msg).json()
    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]
    assert second["metadata"]["key_id"] is None and second["metadata"]["fallback_attempts"] == 0
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert second["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]


def test_different_message_not_cached(client):
    chat(client, sid(), uniq())
    assert chat(client, sid(), uniq()).json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_multi_turn_and_history(client):
    s = sid()
    m1, m2 = uniq("one"), uniq("two")
    r1 = chat(client, s, m1).json()
    r2 = chat(client, s, m2).json()
    assert "turn=2" in r1["reply"] and "turn=4" in r2["reply"]  # history is sent to the LLM
    hist = client.get(f"/sessions/{s}/messages").json()
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant", "user", "assistant"]
    assert hist["messages"][0]["content"] == m1
    assert hist["messages"][1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert all(m["role"] != "system" for m in hist["messages"])


def test_sessions_are_separate(client):
    a, b = sid(), sid()
    chat(client, a, uniq())
    chat(client, a, uniq())
    r = chat(client, b, uniq()).json()
    assert "turn=2" in r["reply"]
    assert len(client.get(f"/sessions/{b}/messages").json()["messages"]) == 2


def test_tokens_are_per_request_not_cumulative(client):
    a, b = sid(), sid()
    ra = chat(client, a, "What is the capital of France? " + "ab")
    rb = chat(client, b, "What is the capital of Brazil? " + "cd")
    assert abs(ra.json()["metadata"]["input_tokens"] - rb.json()["metadata"]["input_tokens"]) <= 2
    ra2 = chat(client, a, uniq()).json()["metadata"]["input_tokens"]
    assert ra2 > ra.json()["metadata"]["input_tokens"]  # grows with history, but is per-request usage


def test_system_prompt_is_session_scoped_and_changes_cache_key(client):
    msg = uniq()
    a = chat(client, sid(), msg, system_prompt="Be a pirate.").json()
    b = chat(client, sid(), msg).json()
    assert b["metadata"]["resolution_source"] == "LIVE_INFERENCE"  # different prompt => different cache key
    assert a["reply"]


def test_unknown_session_404(client):
    r = client.get("/sessions/nope-nope/messages")
    assert r.status_code == 404 and r.json() == {"detail": "session not found"}


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "s", "message": ""},
        {"session_id": "s", "message": "   "},
        {"session_id": "", "message": "hi"},
        {"message": "hi"},
        {"session_id": "s"},
        {"session_id": "s", "message": "a" * 4001},
        {"session_id": "s" * 129, "message": "hi"},
    ],
)
def test_validation_422(client, payload):
    r = client.post("/chat", json=payload)
    assert r.status_code == 422 and "detail" in r.json()


def test_malformed_json_422(client):
    r = client.post("/chat", content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "detail" in r.json()


def test_failover_key_1_429(client):
    r = chat(client, sid(), uniq(), headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    md = r.json()["metadata"]
    assert md["key_id"] == "key_2" and md["fallback_attempts"] == 1
    assert md["resolution_source"] == "LIVE_INFERENCE"
    assert "mock" in r.json()["reply"]  # a real answer, not an error wrapped in 200


def test_failover_key_1_500(client):
    r = chat(client, sid(), uniq(), headers={"X-Simulate-Failure": "key_1=500"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"


def test_failover_even_when_message_cached(client):
    msg = uniq()
    chat(client, sid(), msg)
    r = chat(client, sid(), msg, headers={"X-Simulate-Failure": "key_1=429"})
    assert r.json()["metadata"]["key_id"] == "key_2"


def test_all_keys_fail_503_and_not_stored(client):
    s = sid()
    for h in ("*=429", "key_1=429,key_2=500"):
        r = chat(client, s, uniq(), headers={"X-Simulate-Failure": h})
        assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert client.get(f"/sessions/{s}/messages").status_code == 404


def test_real_provider_errors_fail_over(client, monkeypatch):
    from app import llm

    calls = []
    real = llm.litellm.completion

    def flaky(**kw):
        calls.append(kw["api_key"])
        if kw["api_key"] == "test-key-1":
            raise RuntimeError("429 quota exceeded")
        return real(**kw)

    monkeypatch.setattr(llm.litellm, "completion", flaky)
    md = chat(client, sid(), uniq()).json()["metadata"]
    assert calls[:2] == ["test-key-1", "test-key-2"]
    assert md["key_id"] == "key_2" and md["fallback_attempts"] == 1


def test_simulation_header_ignored_when_disabled(client, monkeypatch):
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")
    r = chat(client, sid(), uniq(), headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_1"
