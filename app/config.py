"""Application configuration (Pydantic Settings).

Environment variables are prefixed with FOM_.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = Field(default="dev", validation_alias="APP_ENV")
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://fom:fom@localhost:5432/fom",
        validation_alias="DATABASE_URL",
    )
    database_echo: bool = Field(default=False, validation_alias="DATABASE_ECHO")

    # Ingestion
    raw_store_path: str = Field(default="./data/raw", validation_alias="RAW_STORE_PATH")
    max_upload_mb: int = Field(default=100, validation_alias="MAX_UPLOAD_MB")

    # Security / auth (placeholder for release 1; release 0.1 uses local dev mode)
    auth_enabled: bool = Field(default=False, validation_alias="AUTH_ENABLED")
    secret_key: str = Field(default="dev-secret-change-me", validation_alias="SECRET_KEY")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
