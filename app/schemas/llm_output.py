# app/schemas/llm_output.py
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional

# 1. API 요청 스키마
class SummaryRequest(BaseModel):
    url: str = Field(description="요약할 웹사이트 URL")

# 2. LLM이 생성할 구조화된 결과 포맷
class LLMAnalysisOutput(BaseModel):
    summary: str = Field(description="본문 내용을 3줄 내외로 명확하게 요약한 텍스트")
    category: str = Field(description="문서 대분류 (예: 개발/기술, 인공지능, 비즈니스/경제, 뉴스 등)")
    tags: List[str] = Field(description="문서의 핵심 키워드 태그 목록 (최대 5개)")

# 3. API 최종 응답 스키마
class SummaryResponse(BaseModel):
    success: bool
    url: str
    title: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = []
    error_message: Optional[str] = None