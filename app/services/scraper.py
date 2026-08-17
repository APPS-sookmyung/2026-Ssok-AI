# app/services/scraper.py
import trafilatura
from bs4 import BeautifulSoup
import requests
from typing import Tuple, Optional

class WebScraper:
    @staticmethod
    def extract_content(url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        URL에서 제목(title)과 본문 텍스트(content)를 추출합니다.
        Returns: (title, content)
        """
        try:
            # 1. trafilatura로 다운로드 및 본문 텍스트 추출
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                # 일반 requests로 fallback
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                resp = requests.get(url, headers=headers, timeout=10)
                downloaded = resp.text

            # 본문 추출 (include_comments=False로 댓글 제외)
            text_content = trafilatura.extract(
                downloaded, 
                include_comments=False, 
                include_tables=True,
                no_fallback=False
            )

            # 제목 추출을 위해 BeautifulSoup 파싱
            soup = BeautifulSoup(downloaded, 'html.parser')
            title = soup.title.string.strip() if soup.title and soup.title.string else "No Title"

            return title, text_content
        except Exception as e:
            print(f"[Scraper Error] {url}: {e}")
            return None, None