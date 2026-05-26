from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////srv/yqgl/data/yqgl.db"
    data_dir: Path = Path("/srv/yqgl/data")
    cookie_secret: str = "dev-change-me"

    llm_base_url: str = "https://api.deepseek.com/anthropic"
    llm_model: str = "deepseek-v4-pro"
    llm_api_key: str = ""

    asr_base_url: str = "http://127.0.0.1:8001"
    asr_model: str = "Qwen/Qwen3-ASR-1.7B"

    tts_base_url: str = "http://127.0.0.1:8002"

    internal_base_url: str = "http://127.0.0.1:8080"

    cors_allow_origins: list[str] = ["*"]


settings = Settings()
