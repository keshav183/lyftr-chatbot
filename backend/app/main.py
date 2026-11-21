import logging
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import config, db, llm

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

app = FastAPI(title="LLM Chatbot with Key Failover and Response Caching")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    llm.setup_cache()


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str
    system_prompt: str | None = Field(default=None, max_length=8000)

    @field_validator("message")
    @classmethod
    def _trim(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 4000:
            raise ValueError("message must be 1-4000 characters after trimming")
        return v


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    detail = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health():
    keys = len(config.api_keys())
    if not db.db_ok() or keys == 0:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "keys_configured": keys, "cache_enabled": llm.litellm.cache is not None},
        )
    return {"status": "ok", "keys_configured": keys, "cache_enabled": llm.litellm.cache is not None}


@app.post("/chat")
def chat(body: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
    started = time.perf_counter()
    history = db.get_history(body.session_id)
    system_prompt = body.system_prompt if body.system_prompt is not None else db.get_system_prompt(body.session_id)
    effective_system = system_prompt or config.DEFAULT_SYSTEM_PROMPT

    messages = [{"role": "system", "content": effective_system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": body.message})

    try:
        result = llm.complete(messages, llm.parse_simulation(x_simulate_failure))
    except llm.AllProvidersUnavailable:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    # latency_ms = server-measured time for this request (history load + LLM + key failover)
    latency_ms = int((time.perf_counter() - started) * 1000)
    metadata = {
        "resolution_source": result.source,
        "model": result.model,
        "latency_ms": latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "key_id": result.key_id,
        "fallback_attempts": result.fallback_attempts,
    }
    db.save_turn(body.session_id, body.message, result.reply, metadata, body.system_prompt)
    return {"session_id": body.session_id, "reply": result.reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    messages = db.get_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="session not found")
    out = []
    for m in messages:
        item = {"role": m["role"], "content": m["content"]}
        if "metadata" in m:
            md = m["metadata"]
            item["metadata"] = {
                "resolution_source": md.get("resolution_source"),
                "input_tokens": md.get("input_tokens"),
                "output_tokens": md.get("output_tokens"),
            }
        out.append(item)
    return {"session_id": session_id, "messages": out}
