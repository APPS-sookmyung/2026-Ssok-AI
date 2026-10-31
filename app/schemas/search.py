"""문서 기준 의미 검색 요청과 응답."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BookmarkId = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "query": "그 리액트 버전 비교하는 글 뭐였지", "space_ids": [3, 8, 12],
        "top_k": 5, "saved_from": None, "saved_to": None,
    }]})

    query: str = Field(min_length=1)
    space_ids: list[BookmarkId]
    top_k: int = Field(default=5, strict=True, ge=1, le=20)
    saved_from: date | None = None
    saved_to: date | None = None

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("검색어를 입력해주세요.")
        return value

    @field_validator("space_ids")
    @classmethod
    def unique_spaces(cls, values: list[int]) -> list[int]:
        return list(dict.fromkeys(values))

    @field_validator("saved_from", "saved_to", mode="before")
    @classmethod
    def require_calendar_date(cls, value):
        if value is None or type(value) is date:
            return value
        if not isinstance(value, str):
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from None
        if parsed.isoformat() != value:
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
        return parsed

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.saved_from and self.saved_to and self.saved_from > self.saved_to:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        if self.saved_to == date.max:
            raise ValueError("종료일은 9999-12-31보다 이전이어야 합니다.")
        return self


class SearchResult(BaseModel):
    bookmark_id: BookmarkId
    similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
