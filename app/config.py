from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    log_level: str = "info"
    session_secret: str = "dev-insecure-secret-change-me"
    base_url: str = "http://localhost:8000"

    database_url: str = "postgresql+asyncpg://arbordocs:arbordocs@localhost:5432/arbordocs"

    # GitHub App — one registration used for both admin OAuth login and
    # per-project repo installation access (ADR-0007).
    github_app_id: str = ""
    github_app_slug: str = ""
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    github_app_private_key_b64: str = ""
    github_webhook_secret: str = ""

    # Discord — single shared bot application (ADR-0005).
    discord_bot_token: str = ""
    discord_oauth_client_id: str = ""
    discord_oauth_client_secret: str = ""

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    ollama_model: str = "qwen2.5:7b"

    # Phase 2 — discussion reconstruction (Stage 0) + candidate filter (Stage 1).
    # Env-overridable so Phase 3 ablations (recall vs. threshold) don't need code changes.
    embedding_model_name: str = "all-MiniLM-L6-v2"
    reconstruction_inactivity_minutes: int = 30
    reconstruction_similarity_threshold: float = 0.45
    candidate_embedding_threshold: float = 0.5
    worker_poll_interval_seconds: int = 60


settings = Settings()
