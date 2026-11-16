# 북마크 분석과 임베딩 저장

Spring은 북마크를 처음 저장하거나 재분석할 때 `POST /api/v1/ai/analyze`를 호출합니다.

```json
{
  "bookmark_id": 123,
  "url": "https://example.org/react",
  "callback_url": "https://spring.example.org/api/v1/bookmarks/ai-result",
  "space_id": 7,
  "saved_at": "2026-11-14T00:30:00+09:00"
}
```

- `space_id`는 북마크가 속한 스페이스의 양의 정수 ID입니다. `saved_at`은 최초 저장 시각이며 ISO 8601 형식으로 시간대 오프셋 또는 `Z`를 포함합니다.
- 두 필드를 모두 생략한 기존 요청은 요약과 콜백을 계속합니다. 한 필드만 주거나 시간대를 생략하면 422를 반환합니다. `callback_url`은 기존과 같이 필요합니다.
- 서버는 202와 `PROCESSING`을 반환합니다. 분석이 성공하면 제목·요약·태그로 문서 임베딩을 만든 뒤 `content_vectors`에 저장하고 콜백을 보냅니다.
- 문서는 `RETRIEVAL_DOCUMENT`, 검색어는 `RETRIEVAL_QUERY`로 임베딩합니다. 두 호출은 같은 모델과 출력 차원을 사용합니다. 기본값은 `models/gemini-embedding-001`, 768차원입니다.
- 재분석하면 같은 `bookmark_id`의 스페이스·제목·요약·벡터를 갱신합니다. 이미 기록한 최초 저장 시각은 유지하고 기존 행의 `saved_at`이 NULL이면 요청값으로 채웁니다.
- 임베딩 생성·저장 실패 시 변경을 롤백하거나 건너뛰고 분석 성공 콜백을 보냅니다. 분석 자체가 실패하면 벡터를 쓰지 않고 실패 콜백을 보냅니다.

저장 후 Spring이 접근 권한을 확인한 스페이스 ID를 검색 요청에 전달합니다.

```json
{"query": "리액트", "space_ids": [7]}
```

`POST /api/v1/ai/search`는 목록 안의 후보만 반환합니다. 빈 목록의 결과는 빈 배열입니다.

## 테스트

[DB 설정](../sql/README.md)에 따라 pgvector가 설치된 전용 DB의 `TEST_DATABASE_URL`을 지정합니다.

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

`test_analyze_search.py`는 운영 FastAPI 앱의 분석·검색 라우트와 PostgreSQL 저장소를 연결해 테스트합니다. 외부 HTTP 응답과 Gemini 모델 응답은 고정해 재현할 수 있습니다.
