# 의미 검색 개발 상태

## 구현 범위

기존 이슈 #8의 검색 스키마, 독립 라우터, 검색어 임베딩 인터페이스와 PostgreSQL 검색 저장소를 구현했습니다. 운영 진입점과 채아 님의 분석 라우터는 수정하지 않았습니다.

실제 모델 어댑터는 아직 없습니다. 검색어 모델은 북마크 저장에 사용한 모델과 같은 벡터 공간과 출력 차원을 사용해야 합니다. 모델별 검색어 입력 방식을 적용할 수 있도록 embed_query 메서드를 별도로 정의했습니다.

DB에는 PR #11의 title, summary, saved_at 컬럼이 필요합니다. dev 기준으로 분기했고 선행 PR의 코드나 커밋을 합치지는 않았습니다. 검색 테스트에는 PR #11 커밋 2770266의 초기화 SQL을 복사한 고정 스키마를 사용합니다. 머지 후 변경 여부를 확인해야 합니다.

## 요청과 응답

노션 명세 기준 경로는 POST /api/v1/ai/search입니다. 기존 이슈 #8에 적힌 /api/ai/search와 단일 space_id 대신 아래 형식을 구현했습니다. 이슈 본문과 노션은 이번 작업에서 수정하지 않았습니다.

```json
{
  "query": "그 리액트 버전 비교하는 글 뭐였지",
  "space_ids": [3, 8, 12],
  "top_k": 5,
  "saved_from": "2026-09-01",
  "saved_to": "2026-09-30"
}
```

응답 예시입니다. 실제 결과와 유사도는 모델 및 저장 데이터에 따라 달라집니다.

```json
{
  "query": "그 리액트 버전 비교하는 글 뭐였지",
  "results": [{"bookmark_id": 123, "similarity": 0.8}]
}
```

- query는 공백만 있으면 거절합니다. 응답에는 입력 문자열을 그대로 반환합니다.
- space_ids는 필수이며 빈 목록이면 모델과 DB 호출 없이 빈 결과를 반환합니다. 중복 ID는 제거합니다.
- 공간 ID는 양의 BIGINT 범위 정수여야 합니다. 문자열이나 bool은 허용하지 않습니다.
- top_k는 문서 기준 기본 5, 최대 20입니다. 범위를 벗어나면 422를 반환합니다.
- saved_from과 saved_to는 YYYY-MM-DD 형식이며 생략 또는 null이 가능합니다. 시작일이 종료일보다 늦으면 422입니다.
- 현재 날짜 경계의 기본값은 한국 시간 UTC+09:00입니다. 종료일 전체를 포함하도록 다음 날 00시 미만 조건을 사용합니다. SearchPolicy.date_timezone으로 바꿀 수 있으며 팀 합의가 필요합니다.
- 날짜 필터를 사용하면 saved_at이 NULL인 기존 행은 제외합니다. 날짜 필터가 없으면 검색 대상에 포함합니다.
- 준비되지 않은 서비스나 의존 서비스 실패는 503, 전체 검색 제한 시간 초과는 504입니다. 내부 예외 내용은 응답에 포함하지 않습니다.

## 순위 계산

1. SQL에서 space_ids와 날짜 범위를 적용합니다.
2. 검색어 벡터와 저장된 벡터의 코사인 유사도를 구합니다.
3. 유사도 기준 미만 결과와 영벡터를 제외합니다.
4. 제목과 요약에 포함된 검색어 토큰 비율을 키워드 점수로 계산합니다.
5. 혼합 점수, 코사인 유사도, bookmark_id 순으로 정렬한 뒤 top_k를 적용합니다.

현재 기본값은 아래와 같습니다. 실제 검색 품질을 측정해 확정한 값이 아닙니다.

- 최소 코사인 유사도: 0.5
- 키워드 가중치: 0.2
- 혼합 점수: 0.8 * 코사인 유사도 + 0.2 * 키워드 점수
- 모델 호출과 DB 조회를 합한 제한 시간: 30초

응답 similarity는 혼합 점수가 아닌 코사인 유사도입니다. 따라서 응답 목록이 similarity 내림차순과 항상 같지는 않습니다. 키워드 점수만 높은 낮은 유사도 결과는 포함하지 않습니다.

키워드 처리는 중복 제거한 단어의 부분 문자열 일치입니다. 한국어 형태소 분석이나 불용어 처리는 아직 적용하지 않았습니다. SQL 매개변수 바인딩을 사용하고 검색어의 %와 _를 와일드카드로 처리하지 않습니다.

현재는 조건에 맞는 행을 대상으로 정확 검색합니다. 데이터 규모와 모델이 정해지기 전이므로 HNSW 인덱스는 추가하지 않았습니다. 향후 인덱스를 추가할 때 필터 적용 후 결과 개수와 검색 정확도를 다시 검증해야 합니다.

## 독립 실행과 /docs

```powershell
.venv\Scripts\python.exe -m uvicorn app.search_app:create_app --factory --host 127.0.0.1 --port 8001
```

http://127.0.0.1:8001/docs 에서 요청 형식을 확인할 수 있습니다. 모델과 저장소가 연결되지 않은 기본 앱에서도 아래 요청은 200과 빈 결과를 반환합니다.

```json
{"query": "리액트", "space_ids": [], "top_k": 5}
```

공간 ID가 있는 요청은 서비스 연결 전까지 503을 반환합니다. 임의 벡터를 만들어 실제 모델 검색인 것처럼 동작시키지 않습니다. API부터 실제 pgvector 검색까지의 흐름은 테스트에서 고정 벡터 제공자를 주입해 검증합니다.

## 서비스 연결 예시

모델 어댑터가 준비되면 아래와 같이 조립할 수 있습니다. provider는 비동기 embed_query 메서드를 구현해야 합니다. 검색 요청마다 새 엔진을 만들지 말고 앱 수명 동안 공유하고 종료 시 정리해야 합니다.

```python
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.repositories.search import PostgresSearchRepository
from app.search_app import create_app
from app.services.retrieval import SearchService

service = SearchService(
    provider=provider,
    repository=PostgresSearchRepository(AsyncSessionLocal),
    dimensions=settings.EMBEDDING_DIM,
)
app = create_app(service)
```

운영 앱에는 app.api.search.router를 등록하고 app.state.search_service에 준비된 서비스를 지정하면 됩니다. app/main.py 연결은 PR #4 머지 후 진입점을 확인하고 적용해야 합니다.

권한 판단은 문서대로 스프링이 담당합니다. AI는 전달받은 목록 안에서만 검색합니다. 이 목록 자체의 진위를 검증하는 사용자 인증은 구현하지 않았으므로, 운영 연결 시 신뢰할 수 있는 스프링 요청만 AI 서버에 도달하도록 해야 합니다.

## 테스트

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_search*.py" -v
```

DB 테스트를 실행하려면 별도 PostgreSQL 테스트 DB의 연결 문자열을 TEST_DATABASE_URL로 전달합니다. pgvector 설치와 스키마 및 확장 생성 권한이 필요합니다. 테스트마다 임의의 스키마를 생성하고 종료 후 삭제합니다. 운영 DB에서 실행하지 마세요.

단위 테스트는 요청 검증, 빈 권한 목록의 외부 호출 생략, 날짜 경계, 오류 응답, 타임아웃, 취소와 OpenAPI 형식을 확인합니다. DB 테스트는 공간 격리, 날짜 범위와 NULL 저장일, 키워드 순위 보정, 유사도 기준, 최대 결과 수, SQL 매개변수 처리와 API 응답을 확인합니다.

## 남은 작업

- 확정한 모델의 검색어 어댑터 연결과 실제 모델 호출 검증
- 실제 북마크 데이터로 유사도 기준과 키워드 가중치 조정
- 날짜 필터 시간대 합의
- 선행 PR 머지 후 실제 테이블과 운영 앱에 연결
- 데이터 규모에 따른 HNSW 도입 검토

노션 API 상태는 아직 실제 모델과 운영 연동 검증 전이므로 구현 중으로 유지하는 것이 맞습니다. 문서와 이슈 상태는 직접 변경하지 않았습니다.
