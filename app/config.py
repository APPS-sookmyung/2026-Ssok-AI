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

    # 콜백 전송을 예외적으로 허용할 호스트 목록(콤마 구분, 예: "localhost,127.0.0.1").
    # AI 서버와 스프링 서버를 같은 EC2 등 내부망에 배포하면 콜백 주소가 사설
    # IP·루프백으로 해석되어 기본 SSRF 검증(공인 주소만 허용)에 막힌다. 그런
    # 경우에만 실제 배포 환경의 콜백 호스트를 여기 등록한다. 비워두면 기존처럼
    # 공인 주소만 허용한다.
    CALLBACK_ALLOWED_HOSTS: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
