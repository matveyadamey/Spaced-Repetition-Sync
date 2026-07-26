from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    database_url: str = "postgresql+asyncpg://spaced:spaced@localhost:5432/spaced_repetition"
    environment: str = "development"
    log_level: str = "INFO"
    max_new_cards_per_session: int = 20
    plugin_install_url: str = "https://github.com/your-repo/spaced_repetition#obsidian-plugin"
    max_request_body_bytes: int = 10 * 1024 * 1024


settings = Settings()
