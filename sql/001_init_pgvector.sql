-- pgvector 확장 및 임베딩 테이블
-- 실행 전 EMBEDDING_DIM(아래 vector(768)) 이 실제 모델 출력 차원과 같은지 반드시 확인할 것.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS content_vectors (
    bookmark_id BIGINT PRIMARY KEY,          -- 스프링 메인 DB의 북마크 PK
    space_id    BIGINT NOT NULL,             -- 개인/팀 스페이스 구분 (검색 격리용)
    embedding   vector(768) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_content_vectors_space
    ON content_vectors (space_id);

-- 코사인 거리 기준 ANN 인덱스.
-- 데이터가 쌓인 뒤에 만들 예정
-- CREATE INDEX idx_content_vectors_embedding
--     ON content_vectors USING hnsw (embedding vector_cosine_ops);
