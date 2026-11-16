# app/schemas/llm_output.py
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, field_validator, model_validator

# 1. API 요청 스키마
class SummaryRequest(BaseModel):
    bookmark_id: int = Field(description="북마크 식별자")
    url: HttpUrl = Field(description="요약할 웹사이트 URL")
    callback_url: HttpUrl = Field(description="분석 완료 결과를 전달받을 콜백(스프링) URL")
    space_id: int | None = Field(default=None, strict=True, gt=0, le=2**63 - 1,
                                 description="북마크가 속한 스페이스 ID")
    saved_at: AwareDatetime | None = Field(default=None, description="시간대가 포함된 최초 북마크 저장 시각")

    @field_validator("saved_at", mode="before")
    @classmethod
    def read_saved_at(cls, value):
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("saved_at에는 시간대를 포함한 ISO 8601 일시를 보내주세요.")

    @model_validator(mode="after")
    def validate_storage_metadata(self):
        if (self.space_id is None) != (self.saved_at is None):
            raise ValueError("space_id와 saved_at은 함께 보내주세요.")
        if self.space_id is not None and not 0 < self.bookmark_id <= 2**63 - 1:
            raise ValueError("저장할 북마크 ID는 양의 BIGINT여야 합니다.")
        return self

# 2. LLM이 생성할 구조화된 결과 포맷 (API 응답의 analysis 필드로도 그대로 재사용)
class LLMAnalysisOutput(BaseModel):
    summary: str = Field(description="본문 내용을 3줄 내외로 명확하게 요약한 텍스트")
    category: str = Field(description="문서 대분류 (예: 개발/기술, 인공지능, 비즈니스/경제, 뉴스 등)")
    tags: List[str] = Field(description="문서의 핵심 키워드 태그 목록 (최대 5개)")

class AnalysisStatus(str, Enum):
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

# 3. API 응답 스키마
# - 엔드포인트의 즉시 응답(status=PROCESSING, analysis=None)과
#   콜백으로 전송되는 최종 결과(status=SUCCESS/FAILED) 양쪽에 공통으로 사용합니다.
class SummaryResponse(BaseModel):
    bookmark_id: int
    status: AnalysisStatus
    title: Optional[str] = Field(default=None, description="크롤러가 HTML <title> 태그에서 추출한 제목")
    analysis: Optional[LLMAnalysisOutput] = None
    error_message: Optional[str] = None
