# 임베딩 저장 서비스

## 현재 구현 범위

이슈 #12의 독립 서비스입니다. 제목, 요약, 태그를 모델 입력으로 구성하고 생성한 벡터를 검증한 뒤 북마크 ID 기준으로 저장합니다. 같은 ID를 다시 저장하면 공간, 제목, 요약, 저장일과 벡터를 함께 갱신합니다. created_at은 유지하고 updated_at은 갱신합니다.

실제 모델 어댑터와 분석 라우터 연결은 아직 구현하지 않았습니다. 새 API가 없으므로 현재 `/docs`에서 호출할 요청 예시는 없습니다. API 연결 후 문서 명세에 맞는 예시를 추가해야 합니다.

## 선행 조건

- PR #11의 메타데이터 마이그레이션을 DB에 먼저 적용해야 합니다.
- 모델의 출력 차원, settings.EMBEDDING_DIM과 DB 벡터 차원이 같아야 합니다. 이번 작업에서는 기존 모델 설정과 768차원을 변경하지 않았습니다.
- space_id와 시간대가 포함된 실제 북마크 저장일 saved_at이 필요합니다. 현재 시각으로 대체하지 않습니다. 분석 요청에 이 값을 전달하는 방식은 채아 님과 협의해야 합니다.

## 사용 방법

모델 어댑터는 비동기 `embed_document(text)`를 제공해야 합니다. 동기 SDK를 그대로 호출하지 않고 비동기 SDK나 별도 스레드 실행을 사용해야 합니다. 모델 선택과 어댑터 구현은 후속 작업입니다.

```python
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.repositories.content_vectors import ContentVectorRepository
from app.services.embedding import EmbeddingService

store = ContentVectorRepository(AsyncSessionLocal, settings.EMBEDDING_DIM)
service = EmbeddingService(provider, store, settings.EMBEDDING_DIM)
await service.save(content)
```

`provider`는 모델 어댑터, `content`는 `app.schemas.embedding.BookmarkContent` 객체입니다. tags는 문자열 튜플입니다. 모델 호출 제한 시간은 기본 30초이며 생성이 끝난 뒤 DB 트랜잭션을 엽니다.

저장 쿼리는 파라미터 바인딩을 사용합니다. dev의 ORM 모델에 아직 없는 메타데이터 컬럼은 SQL에 명시했습니다. PR #11 머지 후 실제 마이그레이션과 함께 다시 검증해야 합니다.

## 실패 처리

빈 입력, 차원 불일치, 숫자가 아닌 원소, 비유한 값, float32 범위 초과와 영벡터를 거부합니다. 생성이나 검증 실패 시 DB를 변경하지 않습니다. 저장 실패 시 해당 트랜잭션을 롤백합니다.

`EmbeddingService.save()`는 실패와 작업 취소를 호출자에게 전달합니다.

`save_embedding_and_notify()`는 분석 성공 후 사용할 독립 처리 함수입니다. 메타데이터 변환, 임베딩 생성 또는 저장이 실패하면 예외 종류를 기록하고 준비된 콜백을 한 번 호출합니다. 분석 원문이나 DB 매개변수가 포함될 수 있는 예외 본문은 기록하지 않습니다. 반환값은 임베딩 저장 성공 여부입니다.

저장 전체 제한 시간은 기본 40초이며 모델 호출의 기본 30초 제한과 별개입니다. 제한 시간은 비동기 작업의 취소를 요청하는 방식이므로 어댑터가 취소에 협조해야 합니다. 외부에서 들어온 작업 취소는 그대로 전파하고 콜백을 강제로 보내지 않습니다. 콜백 자체의 예외도 전파하며 재시도하지 않습니다. 콜백의 HTTP 전송 제한 시간과 재시도 정책은 전송 함수가 담당합니다.

현재 테스트는 이 함수에 주입한 콜백의 호출과 본문 유지까지 확인합니다. 실제 라우터와 HTTP 전송은 연결하지 않았으며 서버 전체 흐름을 검증한 것은 아닙니다.

## 테스트

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

DB 테스트에는 별도 테스트 DB의 TEST_DATABASE_URL을 설정합니다. PostgreSQL에 pgvector가 설치되어 있고 테스트 계정에 스키마와 확장 생성 권한이 있어야 합니다. 각 테스트는 임의 이름의 스키마를 만들고 종료 후 삭제합니다. 운영 DB를 사용하지 마세요.

`tests/fixtures/content_vectors_metadata.sql`은 PR #11의 초기화 SQL을 복사한 테스트 전용 스키마입니다. 머지 후 실제 마이그레이션과 달라지지 않았는지 확인해야 합니다.

단위 테스트에서는 입력 구성, 벡터 검증, 모델 오류, 타임아웃과 취소를 확인합니다. DB 테스트에서는 신규 저장과 중복 갱신, 생성 실패 시 기존 행 보존, DB 제약 위반 시 롤백과 다음 저장의 복구를 확인합니다.

## 머지 후 연결할 위치

PR #4의 `_analyze_and_notify()`에서 분석 성공 결과를 만든 뒤, 기존 콜백 호출 위치에 아래 처리를 연결할 수 있습니다. 아래는 협의용 코드이며 현재 라우터에 적용하지 않았습니다. 분석 실패 경로는 기존 실패 콜백을 유지합니다.

```python
from app.schemas.embedding import BookmarkContent
from app.services.analysis_completion import save_embedding_and_notify

# result는 기존 SUCCESS 분석 결과입니다.
# req.space_id와 req.saved_at은 요청 계약 협의 후 추가할 필드입니다.
await save_embedding_and_notify(
    build_content=lambda: BookmarkContent(
        bookmark_id=req.bookmark_id,
        space_id=req.space_id,
        title=title,
        summary=analysis.summary,
        tags=tuple(analysis.tags),
        saved_at=req.saved_at,
    ),
    embedding_service=embedding_service,
    notify=lambda: _send_callback(str(req.callback_url), result),
)
```

이 경로 뒤에 기존 `_send_callback()`을 다시 호출하면 콜백이 중복되므로 성공 경로에서는 위 함수가 한 번만 호출되도록 연결해야 합니다. `EmbeddingService.save()` 오류를 요약 실패 처리용 except 안에서 처리하면 SUCCESS가 FAILED로 바뀔 수 있어 독립된 실패 범위를 유지해야 합니다.

## 채아 님과 협의할 변경

| 파일 | 변경 이유와 제안 | 현재 상태 |
| --- | --- | --- |
| app/schemas/llm_output.py | 분석 요청에 space_id와 시간대가 포함된 saved_at을 받기 | 미수정, 필수 여부와 누락 요청 처리 협의 필요 |
| app/routes.py | 크롤링 제목과 분석 결과로 BookmarkContent를 구성하고 저장 후 콜백 호출 | 미수정, 성공 경로에 연결할 위치만 정리 |
| app/services/llm_agent.py | 현재 임베딩 서비스 연결에는 변경 불필요 | 미수정 |
| app/services/scraper.py | 현재 반환하는 제목을 저장 입력으로 재사용 가능 | 미수정 |

현재 명세의 분석 요청에는 space_id와 saved_at이 없습니다. 필수로 추가하면 기존 요청이 422가 될 수 있으므로 문서의 추가 제안만으로 호환성이 보장되지는 않습니다. 구버전 요청에서 임베딩만 건너뛸지, 서버와 동시에 필수 필드로 전환할지 먼저 합의해야 합니다. 누락 값을 임의의 공간 ID나 현재 시각으로 채우지 않습니다.

모델 확정 후 실제 비동기 어댑터를 주입하고 출력 차원, 설정과 DB 차원을 함께 확인해야 합니다. 모델 비교와 차원 변경은 보류 상태입니다.

## 마이그레이션 경로 테스트

신규 테이블용 테스트 외에 아래 고정 버전의 SQL을 사용한 기존 DB 경로도 검증합니다.

- 기존 테이블: dev 커밋 d74ef44의 sql/001_init_pgvector.sql
- 메타데이터 마이그레이션: PR #11 커밋 2770266의 sql/002_add_vector_metadata.sql
- 테스트 복사본: tests/fixtures/content_vectors_before_metadata.sql, tests/fixtures/add_vector_metadata.sql

마이그레이션 전에 저장한 행의 메타데이터는 NULL로 유지되는지 확인합니다. 신규 및 마이그레이션 테이블 양쪽에서 저장과 갱신, 실패 시 롤백, DB 잠금으로 인한 제한 시간 초과 시 콜백 호출과 후속 정상 저장을 검증합니다. 머지 시 SQL이 변경되면 복사본을 동기화하고 다시 실행해야 합니다.

## 완료 판단

- 독립 서비스: 입력 구성, 벡터 검증, upsert와 실패 시 콜백 호출 처리 구현
- 실제 분석 API: 요청 필드 협의, 모델 어댑터와 라우터 연결 후 검증 필요
- API 문서 화면: 실제 라우터 연결 후 예시 추가 필요
- 노션 상태: 현재는 실제 분석 후 임베딩 저장을 완료로 표시하지 않음
