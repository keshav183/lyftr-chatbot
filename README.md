# LLM Chatbot with Key Failover and Response Caching

React + FastAPI + LiteLLM + SQLite. Multi-turn chat with an API-key pool that fails over automatically, a LiteLLM response cache, and per-request metadata (source, model, latency, tokens) shown next to every reply.

## 1. Live URLs

- Frontend: `<add your deployed frontend URL>`
- Backend: `<add your deployed backend URL>` (try `/health`)
- Repo: `<add your GitHub URL>`

## 2. Run locally

**With Docker** (needs Docker + make):

```bash
cp .env.example .env        # put at least 2 real keys in LLM_API_KEYS
make up                     # frontend http://localhost:3000, backend http://localhost:8000
make down
```

The SQLite file (and disk cache) live in the named volume `appdata`, mounted at `/data`, so history survives restarts.

**Without Docker:**

```bash
# backend (Python 3.12)
cd backend && pip install -r requirements.txt
export LLM_API_KEYS=key1,key2 DATABASE_URL=sqlite:///./app.db ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000

# frontend (Node 20)
cd frontend && npm install && VITE_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

Tests (offline, no keys needed): `make test` or `cd backend && python -m pytest`.
`MOCK_LLM=true` makes LiteLLM return canned replies through the real cache + failover path.

Environment variables: see `.env.example` (`LLM_API_KEYS`, `LLM_MODEL`, `DATABASE_URL`, `ALLOWED_ORIGINS`, `ENABLE_FAILURE_SIMULATION`, `CACHE_TYPE`, `CACHE_DIR`, `VITE_API_URL`, `MOCK_LLM`).

## 3. Design decisions

**Key fallback.** `LLM_API_KEYS` is split into `key_1..key_n`. For each request the backend calls `litellm.completion(api_key=...)` with the keys in order. Any provider failure (429, quota, 5xx, timeout, auth) moves on to the next key; `fallback_attempts` counts keys that failed first. If every key fails the API returns `503 {"detail": "all providers unavailable"}` and nothing is written to history. Keys are never returned or logged; only `key_N` ids are. Retries inside LiteLLM are off (`num_retries=0`) so failover happens immediately instead of burning time on a dead key.

**Caching.** LiteLLM's built-in `Cache` (in-memory by default, disk with `CACHE_TYPE=disk`). The cache key is model + the full message list (system prompt + history + new message), so the same first message in a new session hits, and any different message or system prompt misses. LiteLLM does not include the API key in the cache key, so a response cached via `key_1` is reused when `key_2` would be called. Hits are detected through LiteLLM's `cache_hit` flag; tokens are the usage stored with the cached response, `key_id` is `null`, `fallback_attempts` is `0`.

**SQLite session storage.** `messages` table exactly as specified (plus an index) and a small `sessions` table holding a per-session system prompt. Schema is created on startup; path comes from `DATABASE_URL` (`/data/app.db` in Docker). A user + assistant pair is written in one transaction only after a successful reply, so 422/503 never touch history. History is replayed to the model on every turn, and the client only sends the new message.

**Failure simulation.** `X-Simulate-Failure` is parsed only when `ENABLE_FAILURE_SIMULATION=true`. Listed keys are skipped as if the provider returned that status, for that one request. Simulated requests bypass the cache so they always return a real live answer (`key_1=429` returns `key_2`) even if the same message was cached earlier.

**Other.** Latency is measured server-side per request. Validation errors are returned as plain JSON, and a catch-all handler ensures no stack traces or HTML error pages.

## 4. Verification

```bash
B=http://localhost:8000
# per-message tokens + live call
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a1","message":"What is the capital of France?"}'
# cache hit: same message, new session -> LLM_CACHE, same reply, key_id null, lower latency
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a2","message":"What is the capital of France?"}'
# failover: answered by key_2, fallback_attempts 1
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' -d '{"session_id":"a3","message":"Hello"}'
# all keys fail: 503 and nothing stored
curl -si $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"a4","message":"Hello"}'
curl -s $B/sessions/a4/messages      # 404 session not found
curl -s $B/sessions/a1/messages      # stored history
```

In the UI, open "Session settings" and type `key_1=429` into the X-Simulate-Failure field to demo failover; send the same first message from two tabs to demo a cache hit. Each reply shows source, model, latency and input/output tokens for that request only.

## 5. Setup Used

Editor + AI assistants: `<fill in, e.g. VS Code, Claude>`. LiteLLM 1.110, FastAPI, Vite + React 18.

## 6. Bonus features

- Optional per-session system prompt field in the UI.
- In-UI failure-simulation field for demos.
- Disk-backed cache option that survives restarts.
- Offline `MOCK_LLM` mode so the full test suite runs without keys.
- 23 backend tests covering contract, caching, failover, 422/503/404 and token accounting.

## Deployment notes

- **Backend:** deploy `backend/` as a Docker service (Render, Railway, Fly.io, HF Spaces). Set `LLM_API_KEYS`, `ALLOWED_ORIGINS=<frontend URL>`, `ENABLE_FAILURE_SIMULATION=true`, `DATABASE_URL`. Attach a persistent disk at `/data` if the host offers one. The container honors `$PORT`.
- **Frontend:** deploy `frontend/` (Vercel/Netlify/Cloudflare Pages) with build command `npm run build`, output `dist`, and env `VITE_API_URL=<backend URL>`.
