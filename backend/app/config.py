"""Environment-driven configuration. Read at call time so tests can override it."""
import os

DEFAULT_SYSTEM_PROMPT = "You are a helpful, concise assistant."


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


def api_keys() -> list[str]:
    return [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]


def model() -> str:
    return os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash")


def database_path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    # sqlite:////data/app.db -> /data/app.db ; sqlite:///./app.db -> ./app.db
    return url.split("sqlite:///", 1)[1] if url.startswith("sqlite:///") else url


def allowed_origins() -> list[str]:
    return [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]


def failure_simulation_enabled() -> bool:
    return _bool("ENABLE_FAILURE_SIMULATION")


def mock_llm() -> bool:
    """Offline mode for tests/demos: LiteLLM returns a canned reply (cache still applies)."""
    return _bool("MOCK_LLM")


def cache_type() -> str:
    return os.getenv("CACHE_TYPE", "local")  # "local" (in-memory) or "disk"


def cache_dir() -> str:
    return os.getenv("CACHE_DIR", "/data/litellm_cache")
