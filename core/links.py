"""사용자가 직접 열어 볼 확인 링크.

민간 채용 사이트는 자동 조회(크롤링)하지 않는다(robots.txt·이용약관 존중). 여기서는 사용자가 누르는
링크만 만든다. 사이트 안 검색 주소 형식은 확인하지 않았으므로 민간·공공 사이트는 첫 화면으로만 연결하고,
검색어가 들어가는 링크는 네이버 통합검색 하나만 쓴다.
"""
from __future__ import annotations

from urllib.parse import quote_plus

NAVER_SEARCH = "https://search.naver.com/search.naver?query="

SITE_LINKS = [
    {"name": "고용24 (공공 채용정보)", "url": "https://www.work24.go.kr", "hint": "업체명으로 공식 채용 공고가 있는지 검색해 보세요"},
    {"name": "알바몬", "url": "https://www.albamon.com", "hint": "같은 업체가 정식 공고를 올렸는지 확인해 보세요"},
    {"name": "잡코리아", "url": "https://www.jobkorea.co.kr", "hint": "같은 업체가 정식 공고를 올렸는지 확인해 보세요"},
    {"name": "홈택스 (사업자 상태 직접 조회)", "url": "https://www.hometax.go.kr", "hint": "사업자등록번호로 휴·폐업 여부를 직접 조회할 수 있습니다"},
]


def manual_check_links(company_name: str | None, brand_name: str | None = None) -> list[dict]:
    links: list[dict] = []
    for term in [t for t in (company_name, brand_name) if t]:
        links.append({"name": f"네이버에서 '{term} 채용' 검색", "url": NAVER_SEARCH + quote_plus(f"{term} 채용"),
                      "hint": "공식 홈페이지·공식 채용 페이지·대표번호를 찾아 공고 내용과 비교하세요"})
        links.append({"name": f"네이버에서 '{term} 사기' 검색", "url": NAVER_SEARCH + quote_plus(f"{term} 사기"),
                      "hint": "같은 이름으로 피해 사례가 있는지 확인하세요"})
    return links + SITE_LINKS
