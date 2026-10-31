"""임베딩 저장에 필요한 내부 데이터와 벡터 검증."""

from dataclasses import dataclass
from datetime import datetime
import math
from numbers import Real
from collections.abc import Sequence


@dataclass(frozen=True)
class BookmarkContent:
    bookmark_id: int
    space_id: int
    title: str
    summary: str
    tags: tuple[str, ...]
    saved_at: datetime

    def __post_init__(self) -> None:
        for value in (self.bookmark_id, self.space_id):
            if type(value) is not int or not 0 < value <= 2**63 - 1:
                raise ValueError("북마크와 스페이스 ID는 양의 BIGINT여야 합니다.")
        if not isinstance(self.title, str) or not isinstance(self.summary, str):
            raise ValueError("제목과 요약은 문자열이어야 합니다.")
        if not isinstance(self.tags, tuple) or any(not isinstance(tag, str) for tag in self.tags):
            raise ValueError("태그는 문자열 튜플이어야 합니다.")
        if not isinstance(self.saved_at, datetime) or self.saved_at.utcoffset() is None:
            raise ValueError("실제 북마크 저장일과 시간대가 필요합니다.")


def validate_embedding(values: Sequence[float], dimensions: int) -> tuple[float, ...]:
    if type(dimensions) is not int or dimensions <= 0:
        raise ValueError("벡터 차원은 양의 정수여야 합니다.")
    if isinstance(values, (str, bytes)) or len(values) != dimensions:
        raise ValueError("설정된 벡터 차원과 생성 결과가 다릅니다.")
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("벡터 원소는 숫자여야 합니다.")
        number = float(value)
        if not math.isfinite(number) or abs(number) > 3.4028234663852886e38:
            raise ValueError("벡터 원소는 유한한 float32 범위여야 합니다.")
        result.append(number)
    if not any(abs(value) >= 1.401298464324817e-45 for value in result):
        raise ValueError("코사인 검색에는 영벡터를 사용할 수 없습니다.")
    return tuple(result)
