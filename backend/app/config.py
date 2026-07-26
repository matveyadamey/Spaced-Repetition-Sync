from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Convert PaaS postgres URLs to SQLAlchemy asyncpg form."""
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    # asyncpg expects ssl=..., while many hosts provide sslmode=...
    url = url.replace("sslmode=require", "ssl=require")
    url = url.replace("sslmode=verify-full", "ssl=require")
    url = url.replace("sslmode=verify-ca", "ssl=require")
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    database_url: str = "postgresql+asyncpg://spaced:spaced@localhost:5432/spaced_repetition"
    environment: str = "development"
    log_level: str = "INFO"
    max_new_cards_per_session: int = 20
    plugin_install_url: str = (
        "https://github.com/matveyadamey/Spaced-Repetition-Sync#установка-через-brat"
    )
    max_request_body_bytes: int = 10 * 1024 * 1024

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_database_url(value)
        return value


settings = Settings()
