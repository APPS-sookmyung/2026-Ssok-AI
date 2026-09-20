# app/schemas/llm_output.py
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl

# 1. API 요청 스키마
class SummaryRequest(BaseModel):
    bookmark_id: int = Field(description="북마크 식별자")
    url: HttpUrl = Field(description="요약할 웹사이트 URL")
    callback_url: HttpUrl = Field(description="분석 완료 결과를 전달받을 콜백(스프링) URL")

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
    analysis: Optional[LLMAnalysisOutput] = None
    error_message: Optional[str] = None
