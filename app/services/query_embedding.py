"""문서와 검색어에 같은 Gemini 모델과 출력 차원을 사용합니다."""

from collections.abc import Sequence

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import settings

class GeminiEmbeddingProvider:
    def __init__(self) -> None:
        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            google_api_key=settings.GOOGLE_API_KEY,
        )

    async def embed_document(self, text: str) -> Sequence[float]:
        vector, = await self._embeddings.aembed_documents(
            [text],
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=settings.EMBEDDING_DIM,
        )
        return vector

    async def embed_query(self, query: str) -> Sequence[float]:
        # gemini-embedding-001의 기본 출력은 3072차원이므로 저장된 벡터(768차원)와
        # 맞추려면 output_dimensionality를 반드시 지정해야 합니다.
        return await self._embeddings.aembed_query(
            query,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=settings.EMBEDDING_DIM,
        )


GeminiQueryEmbeddingProvider = GeminiEmbeddingProvider
