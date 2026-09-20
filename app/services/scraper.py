# app/services/scraper.py
import ipaddress
import socket
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5
FETCH_TIMEOUT = 10


class UnsafeUrlError(Exception):
    """요청 대상 URL이 SSRF 방지 정책에 의해 차단되었을 때 발생합니다."""


def _is_public_host(hostname: str) -> bool:
    """호스트명이 가리키는 모든 IP가 공인(퍼블릭) 주소인지 확인합니다."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def _assert_safe_url(url: str) -> None:
    """
    스킴과 대상 호스트의 실제 IP를 검사해 내부망/루프백/예약 주소로의
    요청(SSRF)을 차단합니다. 리다이렉트를 따라갈 때마다 다시 호출해야 합니다.

    참고: 여기서 확인한 IP와 실제 커넥션이 맺어지는 시점 사이에는 DNS
    재바인딩(TOCTOU) 여지가 이론적으로 남아 있습니다. 완전한 방지는
    검증된 IP로 커넥션을 고정(pin)하는 커스텀 트랜스포트가 필요하며,
    이는 별도 개선 과제로 남겨둡니다.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"허용되지 않는 URL 스킴입니다: {parsed.scheme}")
    if not parsed.hostname or not _is_public_host(parsed.hostname):
        raise UnsafeUrlError("내부망 또는 예약된 주소로의 요청은 허용되지 않습니다.")


def _fetch_html(url: str) -> bytes:
    """SSRF 검증을 통과한 안전한 대상에서만 원문 HTML을 가져옵니다.

    자동 리다이렉트를 끄고 매 홉(hop)마다 대상 URL을 재검증하여,
    처음엔 공인 주소였다가 리다이렉트로 내부 주소로 우회하는 공격을 막습니다.

    디코딩하지 않은 원본 바이트(resp.content)를 그대로 반환합니다. 서버가
    Content-Type에 charset을 명시하지 않으면 requests는 기본값(ISO-8859-1)으로
    잘못 디코딩해 한글이 깨지므로, 인코딩 판별은 메타 태그/바이트를 직접 보는
    trafilatura·BeautifulSoup에 맡깁니다.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    current_url = url

    for _ in range(MAX_REDIRECTS + 1):
        _assert_safe_url(current_url)
        resp = requests.get(
            current_url,
            headers=headers,
            timeout=FETCH_TIMEOUT,
            allow_redirects=False,
        )

        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("Location")
            if not location:
                break
            current_url = urljoin(current_url, location)
            continue

        resp.raise_for_status()
        return resp.content

    raise UnsafeUrlError("리다이렉트 횟수가 허용 범위를 초과했습니다.")


class WebScraper:
    @staticmethod
    def extract_content(url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        URL에서 제목(title)과 본문 텍스트(content)를 추출합니다.
        Returns: (title, content)
        """
        try:
            downloaded = _fetch_html(url)

            # 본문 추출 (include_comments=False로 댓글 제외)
            # bytes를 그대로 넘겨 trafilatura가 메타 태그/BOM 기반으로 인코딩을 판별하게 합니다.
            text_content = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            )

            # 제목 추출을 위해 BeautifulSoup 파싱 (마찬가지로 bytes를 넘겨 인코딩 자동 판별)
            soup = BeautifulSoup(downloaded, 'html.parser')
            title = soup.title.string.strip() if soup.title and soup.title.string else "No Title"

            return title, text_content
        except Exception as e:
            print(f"[Scraper Error] {url}: {e}")
            return None, None
