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

서비스는 실패를 호출자에게 전달하고 작업 취소도 그대로 전파합니다. 분석 흐름에 연결할 때에는 임베딩 저장 예외를 처리한 뒤 기존 요약 성공 콜백을 계속 보내야 합니다. 콜백 유지 여부는 라우터 연결 후 별도로 검증해야 하며 현재 테스트가 이를 보장하지는 않습니다.

## 테스트

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

DB 테스트에는 별도 테스트 DB의 TEST_DATABASE_URL을 설정합니다. PostgreSQL에 pgvector가 설치되어 있고 테스트 계정에 스키마와 확장 생성 권한이 있어야 합니다. 각 테스트는 임의 이름의 스키마를 만들고 종료 후 삭제합니다. 운영 DB를 사용하지 마세요.

`tests/fixtures/content_vectors_metadata.sql`은 PR #11의 초기화 SQL을 복사한 테스트 전용 스키마입니다. 머지 후 실제 마이그레이션과 달라지지 않았는지 확인해야 합니다.

단위 테스트에서는 입력 구성, 벡터 검증, 모델 오류, 타임아웃과 취소를 확인합니다. DB 테스트에서는 신규 저장과 중복 갱신, 생성 실패 시 기존 행 보존, DB 제약 위반 시 롤백과 다음 저장의 복구를 확인합니다.
