"""LiteLLM gateway: key pool with ordered failover + built-in response cache."""
import logging
import time
from dataclasses import dataclass

import litellm
from litellm.caching.caching import Cache

from . import config

logger = logging.getLogger("llm")
litellm.suppress_debug_info = True

VALID_SIM_STATUSES = {429, 500, 502, 503}


class AllProvidersUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    reply: str
    source: str  # LIVE_INFERENCE | LLM_CACHE
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int
    latency_ms: int


def setup_cache() -> None:
    if config.cache_type() == "disk":
        litellm.cache = Cache(type="disk", disk_cache_dir=config.cache_dir())
    else:
        litellm.cache = Cache(type="local")


def parse_simulation(header: str | None) -> dict[str, int]:
    """'key_1=429,key_2=500' / '*=429' -> {'key_1': 429, ...}. Ignored unless enabled."""
    if not header or not config.failure_simulation_enabled():
        return {}
    out: dict[str, int] = {}
    for part in header.split(","):
        if "=" not in part:
            continue
        key, _, status = part.strip().partition("=")
        try:
            code = int(status.strip())
        except ValueError:
            continue
        if code in VALID_SIM_STATUSES:
            out[key.strip()] = code
    return out


def _simulated_status(sim: dict[str, int], key_id: str) -> int | None:
    return sim.get(key_id, sim.get("*"))


def complete(messages: list[dict], simulate: dict[str, int] | None = None) -> LLMResult:
    """Try each key in order; fail over on any provider error. Raises AllProvidersUnavailable."""
    sim = simulate or {}
    keys = config.api_keys()
    model = config.model()
    start = time.perf_counter()
    failed = 0

    extra: dict = {}
    if sim:
        # Simulation requests must produce a real, live answer: bypass the cache for them.
        extra["cache"] = {"no-cache": True, "no-store": True}
    if config.mock_llm():
        extra["mock_response"] = f"[mock] turn={len(messages)} echo={messages[-1]['content'][:200]}"

    for idx, api_key in enumerate(keys, start=1):
        key_id = f"key_{idx}"
        status = _simulated_status(sim, key_id)
        if status is not None:
            logger.warning("simulated failure %s on %s", status, key_id)
            failed += 1
            continue
        try:
            resp = litellm.completion(
                model=model, messages=messages, api_key=api_key, num_retries=0, timeout=45, **extra
            )
        except Exception as exc:  # 429 / quota / 5xx / auth / network: try the next key
            logger.warning("%s failed (%s: %s)", key_id, type(exc).__name__, str(exc)[:200])
            failed += 1
            continue

        text = (resp.choices[0].message.content or "").strip()
        if not text:  # empty completion is treated as a provider failure
            failed += 1
            continue
        hit = bool(getattr(resp, "_hidden_params", {}).get("cache_hit"))
        usage = resp.usage
        in_tok, out_tok = int(usage.prompt_tokens or 0), int(usage.completion_tokens or 0)
        if config.mock_llm():  # LiteLLM's canned mock usage is constant; count properly for offline runs
            in_tok = litellm.token_counter(model=model, messages=messages)
            out_tok = litellm.token_counter(model=model, text=text)
        return LLMResult(
            reply=text,
            source="LLM_CACHE" if hit else "LIVE_INFERENCE",
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            key_id=None if hit else key_id,
            fallback_attempts=0 if hit else failed,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    raise AllProvidersUnavailable()
