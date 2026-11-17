"""Spring과 FastAPI 사이의 요청 인증 및 결과 수신처 설정."""

from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SpringConnection(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    AI_SERVICE_SECRET: SecretStr | None = None
    AI_CALLBACK_URL: HttpUrl | None = None
    AI_CALLBACK_SECRET: SecretStr | None = None


service_key = APIKeyHeader(name="X-AI-Service-Secret", auto_error=False)


async def get_spring_connection(request: Request) -> SpringConnection:
    if not hasattr(request.app.state, "spring_connection"):
        request.app.state.spring_connection = SpringConnection()
    return request.app.state.spring_connection


def require_spring(token: Annotated[str | None, Security(service_key)],
                   spring: Annotated[SpringConnection, Depends(get_spring_connection)]) -> None:
    configured = spring.AI_SERVICE_SECRET
    if configured is None or not configured.get_secret_value().strip():
        raise HTTPException(status_code=503, detail="Spring 호출 인증이 설정되지 않았습니다.")
    if token is None or not compare_digest(token.encode(), configured.get_secret_value().encode()):
        raise HTTPException(status_code=401, detail="Spring 호출 인증에 실패했습니다.")
