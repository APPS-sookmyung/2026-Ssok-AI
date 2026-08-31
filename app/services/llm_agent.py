# app/services/llm_agent.py
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import settings
from app.schemas.llm_output import LLMAnalysisOutput

class LLMAgent:
    def __init__(self):
        #Gemini모델 초기화
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-3.6-flash",
            temperature=0.2,
            google_api_key=settings.GOOGLE_API_KEY
        )
        self.structured_llm = self.llm.with_structured_output(LLMAnalysisOutput)

    async def summarize_and_tag(self, title: str, content: str) -> LLMAnalysisOutput:
        """본문을 기반으로 핵심 요약, 카테고리, 태그를 생성합니다."""
        # 본문이 너무 길 경우 앞부분 약 12,000자(토큰 절약 및 속도 향상)로 제한
        truncated_content = content[:12000]

        system_prompt = (
            "당신은 기술 문서, 블로그 포스트, 뉴스 기사를 요약하고 분류하는 전문가입니다. "
            "주어진 글의 핵심 내용을 한국어로 명확하게 3줄 내외로 요약하고, "
            "적절한 카테고리와 검색에 유용한 키워드 태그를 3~5개 추출하세요."
        )

        user_content = f"제목: {title}\n\n본문:\n{truncated_content}"

        messages = [
            ("system", system_prompt),
            ("human", user_content)
        ]

        # 비동기 LLM 호출
        result: LLMAnalysisOutput = await self.structured_llm.ainvoke(messages)
        return result