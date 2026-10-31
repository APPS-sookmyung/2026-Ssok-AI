-- 기존 content_vectors 테이블에 검색용 메타데이터를 추가합니다.
-- 실제 북마크 저장 시각을 알 수 없는 기존 행은 saved_at을 NULL로 유지합니다.
-- 실행: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/002_add_vector_metadata.sql

BEGIN;

ALTER TABLE content_vectors
    ADD COLUMN IF NOT EXISTS title TEXT,
    ADD COLUMN IF NOT EXISTS summary TEXT,
    ADD COLUMN IF NOT EXISTS saved_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_content_vectors_saved_at
    ON content_vectors (saved_at);

COMMIT;
