import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    name: str
    instructions_path: str
    repo_path: str | None
    repo_max_chars: int
    db_dsn: str | None
    laravel_base_url: str | None
    laravel_tool_token: str | None
    llm_api_key: str | None
    llm_base_url: str | None
    llm_model: str
    # TTS / Piper
    tts_enabled: bool
    tts_model_path: str | None
    tts_length_scale: float | None  # < 1 = più veloce, > 1 = più lento (default modello se None)


def get_settings() -> Settings:
    return Settings(
        name=os.getenv("DEVIA_NAME", "Kira"),
        instructions_path=os.getenv("DEVIA_INSTRUCTIONS_PATH", "/instructions"),
        repo_path=os.getenv("DEVIA_REPO_PATH", "/repo").strip() or None,
        # Di default carichiamo fino a ~200k caratteri di codice dal repo
        # (Models, Controllers, routes). Puoi ridurre/aumentare via env.
        repo_max_chars=int(os.getenv("DEVIA_REPO_MAX_CHARS", "200000")),
        db_dsn=os.getenv("DEVIA_DB_DSN"),
        laravel_base_url=os.getenv("DEVIA_LARAVEL_BASE_URL"),
        laravel_tool_token=os.getenv("DEVIA_LARAVEL_TOOL_TOKEN"),
        llm_api_key=os.getenv("DEVIA_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
        llm_base_url=os.getenv("DEVIA_LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/") or None,
        llm_model=os.getenv("DEVIA_LLM_MODEL", "llama3.2:3b"),
        tts_enabled=os.getenv("DEVIA_TTS_ENABLED", "0") == "1",
        tts_model_path=os.getenv("DEVIA_TTS_MODEL_PATH"),
        tts_length_scale=_parse_tts_length_scale(os.getenv("DEVIA_TTS_LENGTH_SCALE")),
    )


def _parse_tts_length_scale(value: str | None) -> float | None:
    """Restituisce un float in [0.5, 2.0] o None se non impostato/invalido."""
    if not value:
        return None
    try:
        f = float(value.strip())
        return f if 0.5 <= f <= 2.0 else None
    except ValueError:
        return None
