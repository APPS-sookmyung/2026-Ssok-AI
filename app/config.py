# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    GOOGLE_API_KEY: str
    DATABASE_URL: str
    # text-embedding-004는 Google Gemini API에서 서비스 종료되어
    # gemini-embedding-001로 교체했습니다. EMBEDDING_DIM(768)은 그대로 두고
    # 호출 시 output_dimensionality로 맞춥니다 (기본 출력은 3072차원).
    EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    EMBEDDING_DIM: int = 768

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
