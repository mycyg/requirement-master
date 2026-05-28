from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////srv/yqgl/data/yqgl.db"
    data_dir: Path = Path("/srv/yqgl/data")
    app_env: str = "development"
    cookie_secret: str = "dev-change-me"
    cookie_secure: bool = False

    llm_base_url: str = "https://api.deepseek.com/anthropic"
    llm_model: str = "deepseek-v4-pro"
    llm_api_key: str = ""

    asr_base_url: str = "http://127.0.0.1:8001"
    asr_model: str = "Qwen/Qwen3-ASR-1.7B"

    tts_base_url: str = "http://127.0.0.1:8002"

    internal_base_url: str = "http://127.0.0.1:8080"

    macos_client_download_url: str = (
        "https://github.com/mycyg/requirement-master/releases/download/"
        "client-macos-v0.2.0-unsigned.5/"
        "yqgl-client-macos-universal-unsigned.dmg"
    )
    macos_client_size_bytes: int = 0

    cors_allow_origins: list[str] = ["*"]


settings = Settings()
