# 벡터 DB 초기화 및 마이그레이션

## 적용 전 확인

- 대상 DB와 schema를 확인하고 기존 데이터가 있으면 백업합니다.
- 현재 임베딩 모델 설정과 벡터 차원은 변경하지 않습니다(기본 768).
- 아래 명령의 DB URL은 별도로 주입합니다. 비밀번호를 문서·커밋에 기록하지 않습니다.
- psql에는 `postgresql://...` 형식을 사용합니다. 애플리케이션의
  `postgresql+asyncpg://...` 형식은 psql에서 사용할 수 없습니다.

## 신규 DB

저장소 루트에서 다음 명령을 실행합니다. pgvector 확장 설치 권한이 필요합니다.

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/001_init_pgvector.sql
```

## 기존 DB

이미 테이블이 있으면 001을 다시 실행하는 대신 002를 적용합니다.
001의 CREATE TABLE IF NOT EXISTS는 기존 테이블에 컬럼을 추가하지 않습니다.

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/002_add_vector_metadata.sql
```

002는 하나의 트랜잭션으로 실행하며 재실행할 수 있습니다. 기존 행·벡터·시간
필드는 유지하고 title, summary, saved_at만 NULL 상태로 추가합니다.
기존 데이터가 많은 공유 DB에서는 ALTER TABLE과 색인 생성이 잠금을 사용하므로
실행 시점을 조율합니다. 임의의 기존 동명 컬럼/색인 구조까지 교정하지는 않습니다.

## 필드 의미

| 필드 | PostgreSQL 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| title | TEXT | 허용 | 검색 후보를 설명할 북마크 제목 |
| summary | TEXT | 허용 | 검색 후보를 설명할 요약 |
| saved_at | TIMESTAMPTZ | 허용 | 스프링에서 전달받는 실제 북마크 저장 시각 |

saved_at에는 현재 시각이나 벡터 생성 시각을 기본값으로 넣지 않습니다.
시간대가 있는 datetime을 전달하며, 조회 시 표현 시간대는 DB 세션 설정에 따라
달라도 동일한 시점을 나타냅니다. 날짜 필터용 B-tree 색인은
`idx_content_vectors_saved_at`입니다.

이 변경은 저장 구조만 추가합니다. 메타데이터를 채우는 분석 연동과 날짜 검색 API는
후속 작업입니다. 기존 NULL 값은 출처 데이터를 확보한 뒤 채웁니다.

## 통합 테스트

실제 데이터가 없는 전용 PostgreSQL + pgvector 테스트 DB를 사용합니다.
테스트는 매번 고유 schema를 만들고 종료 시 해당 schema만 삭제합니다.
운영/공유 DB나 애플리케이션 .env의 DB에 실행하지 않습니다.

PowerShell 예시:

```powershell
$env:TEST_DATABASE_URL = "postgresql://test_user:test_password@127.0.0.1:55432/test_db"
python -m unittest discover -s tests -v
Remove-Item Env:TEST_DATABASE_URL
```

TEST_DATABASE_URL이 없으면 통합 테스트를 건너뜁니다. 테스트 DB에는 미리
`CREATE EXTENSION IF NOT EXISTS vector;`를 실행해 두어야 합니다.
프로젝트 requirements.txt의 asyncpg, SQLAlchemy, pgvector가 필요하며
외부 LLM 호출이나 실제 API 키는 사용하지 않습니다.

검증 범위: 기존 행 보존, 002 재실행, 신규 001과 마이그레이션의 컬럼 일치,
ORM의 한국어 텍스트·시간대 포함 저장일 저장/조회, NULL 메타데이터 호환.
