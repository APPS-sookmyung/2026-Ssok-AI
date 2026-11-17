-- Spring에서 영구 삭제한 대상 ID를 기록해 늦게 끝난 분석이 벡터를 다시 쓰지 못하게 합니다.
CREATE TABLE IF NOT EXISTS vector_deletions (
    scope TEXT NOT NULL CHECK (scope IN ('bookmark', 'space')),
    target_id BIGINT NOT NULL CHECK (target_id > 0),
    PRIMARY KEY (scope, target_id)
);
