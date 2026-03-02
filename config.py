from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    database_url: str = Field(default="sqlite:///./micro_saas.db")
    openai_api_key: str = Field(...)
    tavily_api_key: str = Field(...)
    session_ttl_hours: int = Field(default=48)
    global_db_dir: str = Field(default="global_vector_db")
    user_sessions_dir: str = Field(default="user_sessions")

    checkpointer_db_path: str = Field(default="database/checkpointer.db")

    n8n_webhook_url: str = Field(default="")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()