from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Consolidated configuration — single source of truth for all settings."""

    # --- Database ---
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./micro_saas.db")

    # --- API Keys ---
    OPENAI_API_KEY: str = Field(default="")
    ANTHROPIC_API_KEY: str = Field(default="")
    TAVILY_API_KEY: str = Field(default="")
    GOOGLE_API_KEY: str = Field(default="")

    # --- JWT Auth ---
    SECRET_KEY: str = Field(default="")  # MUST be set in .env — no safe default
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 7)  # 1 week

    # --- File Storage & Sessions ---
    USER_SESSIONS_DIR: str = Field(default="user_sessions")
    GLOBAL_DB_DIR: str = Field(default="global_vector_db")
    CHECKPOINTER_DB_PATH: str = Field(default="Database/checkpointer.db")
    SESSION_TTL_HOURS: int = Field(default=48)

    # --- SMTP ---
    SMTP_HOST: str = Field(default="")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM_EMAIL: str = Field(default="")
    SMTP_FROM_NAME: str = Field(default="Legal AI Expert")

    # --- External Services ---
    N8N_WEBHOOK_URL: Optional[str] = Field(default=None)
    RAZORPAY_KEY_ID: str = Field(default="")
    RAZORPAY_KEY_SECRET: str = Field(default="")
    RAZORPAY_WEBHOOK_SECRET: str = Field(default="")
    GOOGLE_CLIENT_ID: str = Field(default="")

    # --- CORS / Security ---
    ALLOWED_ORIGINS: str = Field(default="http://localhost:3000,http://localhost:5173")

    # --- Admin ---
    ADMIN_EMAILS: str = Field(default="")  # Comma-separated emails to auto-promote as admin on startup

    # --- Logging ---
    LOG_LEVEL: str = Field(default="INFO")  # DEBUG, INFO, WARNING, ERROR
    LOG_FILE: Optional[str] = Field(default=None)  # e.g. "logs/app.log" for persistent file logs

    # --- Password Reset ---
    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(default=60)  # 1 hour
    FRONTEND_URL: str = Field(default="http://localhost:5173")  # For reset link in email

    # --- Storage Backend ---
    STORAGE_BACKEND: str = Field(default="local")  # "local" or "s3"
    S3_BUCKET: str = Field(default="")
    S3_REGION: str = Field(default="ap-south-1")
    S3_ACCESS_KEY: str = Field(default="")
    S3_SECRET_KEY: str = Field(default="")
    S3_ENDPOINT_URL: str = Field(default="")  # e.g. https://storage.googleapis.com for GCS

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Derived properties ---

    @property
    def is_production(self) -> bool:
        import os
        return os.getenv("ENV") == "production"

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    @property
    def sync_database_url(self) -> str:
        """Sync version of DATABASE_URL (strips async drivers)."""
        url = self.DATABASE_URL
        if "+asyncpg" in url:
            return url.replace("+asyncpg", "")
        if "+aiosqlite" in url:
            return url.replace("+aiosqlite", "")
        return url

    # --- Backward-compat aliases (lowercase, used by many existing imports) ---

    @property
    def database_url(self) -> str:
        return self.sync_database_url

    @property
    def openai_api_key(self) -> str:
        return self.OPENAI_API_KEY

    @property
    def anthropic_api_key(self) -> str:
        return self.ANTHROPIC_API_KEY

    @property
    def tavily_api_key(self) -> str:
        return self.TAVILY_API_KEY

    @property
    def global_db_dir(self) -> str:
        return self.GLOBAL_DB_DIR

    @property
    def user_sessions_dir(self) -> str:
        return self.USER_SESSIONS_DIR

    @property
    def checkpointer_db_path(self) -> str:
        return self.CHECKPOINTER_DB_PATH

    @property
    def session_ttl_hours(self) -> int:
        return self.SESSION_TTL_HOURS

    @property
    def n8n_webhook_url(self) -> Optional[str]:
        return self.N8N_WEBHOOK_URL

    @property
    def smtp_host(self) -> str:
        return self.SMTP_HOST

    @property
    def smtp_port(self) -> int:
        return self.SMTP_PORT

    @property
    def smtp_user(self) -> str:
        return self.SMTP_USER

    @property
    def smtp_password(self) -> str:
        return self.SMTP_PASSWORD

    @property
    def smtp_from_email(self) -> str:
        return self.SMTP_FROM_EMAIL


settings = Settings()
