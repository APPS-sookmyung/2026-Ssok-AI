"""검색어 임베딩을 생성하는 Gemini 어댑터.

app.services.retrieval.QueryEmbeddingProvider 프로토콜(embed_query)을 구현합니다.
모델 이름과 출력 차원은 settings.EMBEDDING_MODEL / EMBEDDING_DIM을 그대로 따르며,
이 파일에서 새로 결정하지 않습니다. 북마크 본문 임베딩(embed_document)이나
모델 교체는 범위 밖입니다(AI_MASTER_PLAN.md C2, C4 참고).
"""

from collections.abc import Sequence

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import settings

# Gemini 임베딩 API의 task_type. 검색어 전용 값을 사용해 문서 임베딩과
# 같은 벡터 공간에서도 검색어에 맞는 표현을 얻습니다.
_QUERY_TASK_TYPE = "RETRIEVAL_QUERY"


class GeminiQueryEmbeddingProvider:
    def __init__(self) -> None:
        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            google_api_key=settings.GOOGLE_API_KEY,
        )

    async def embed_query(self, query: str) -> Sequence[float]:
        # gemini-embedding-001의 기본 출력은 3072차원이므로 저장된 벡터(768차원)와
        # 맞추려면 output_dimensionality를 반드시 지정해야 합니다.
        return await self._embeddings.aembed_query(
            query,
            task_type=_QUERY_TASK_TYPE,
            output_dimensionality=settings.EMBEDDING_DIM,
        )
