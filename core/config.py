"""앱 전역 설정.

서비스명·팀명·모델·호출 상한·기준값을 이 파일 한 곳에 둔다.
이름이 확정되면 SERVICE_NAME / TEAM_NAME 만 바꾸면 화면·README 생성 문구가 따라 바뀐다.

비밀값(API 키·토큰)은 절대 이 파일에 쓰지 않는다. get_secret() 으로만 읽는다.
읽는 순서: 환경변수 → app/.env → Streamlit Secrets(app/.streamlit/secrets.toml 또는 Cloud 설정).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = APP_DIR / "rules" / "rules.yaml"
SAMPLES_DIR = APP_DIR / "data" / "samples"
TESTSET_DIR = APP_DIR / "data" / "testset"

# ---------------------------------------------------------------------------
# 이름 — 바꿀 때는 여기만 바꾼다 (2026-11-23 확정, 이전 가칭 '지원 전 검문소')
# ---------------------------------------------------------------------------
SERVICE_NAME = "공고돋보기"
SERVICE_NAME_TENTATIVE = False  # True 이면 화면에 "(가칭)"을 붙인다
TEAM_NAME = "CrAI LAB (크라이랩)"
SERVICE_TAGLINE = "지원 전, 구인 공고와 DM의 위험 신호를 판독합니다"


def display_service_name() -> str:
    return f"{SERVICE_NAME} (가칭)" if SERVICE_NAME_TENTATIVE else SERVICE_NAME


# ---------------------------------------------------------------------------
# 최저임금 (근로조건 위법 가능 표시·과도한 급여 신호 계산용)
# 출처: 최저임금위원회 '연도별 최저임금 결정현황' (결정고시일 2025-08-05,
#       적용 2026-01-01~2026-12-31), 2026-11-23 원문 확인
# ---------------------------------------------------------------------------
MINIMUM_WAGE_YEAR = 2026
MINIMUM_WAGE_HOURLY = 10_320  # 원
MINIMUM_WAGE_MONTHLY_209H = 2_156_880  # 원, 주 40시간·주휴 포함 월 209시간 기준
MONTHLY_STANDARD_HOURS = 209
MINIMUM_WAGE_SOURCE = "최저임금위원회 연도별 최저임금 결정현황 (2026년 적용, 결정고시 2025-08-05)"
MINIMUM_WAGE_URL = "https://www.minimumwage.go.kr/minWage/policy/decisionMain.do"

# ---------------------------------------------------------------------------
# AI 모델 (환경변수 MODEL_ID 로 교체 가능)
# ---------------------------------------------------------------------------
DEFAULT_MODEL_ID = "gpt-6.2-sol"

# ---------------------------------------------------------------------------
# 호출 상한 (공개 URL 이라 누구나 호출 가능 → 비용 보호). 3단계에서 확정.
# ---------------------------------------------------------------------------
DEFAULT_SESSION_CALL_LIMIT = 15
DEFAULT_DAILY_CALL_LIMIT = 150

# 입력 길이 상한 (토큰 비용·남용 방지)
MAX_INPUT_CHARS = 4_000

# 출처 채널 (화면 선택지). key 는 규칙 엔진이 쓰는 값.
SOURCE_CHANNELS = {
    "platform": "정식 채용 플랫폼 (알바몬·잡코리아·고용24 등)",
    "sns_messenger": "SNS·메신저 (인스타그램·텔레그램·카카오톡 등)",
    "community": "커뮤니티 (카페·게시판·중고거래 등)",
    "sms": "문자 메시지",
}
# 정식 플랫폼만 공식 경로로 본다 (E54: 직업정보제공사업자의 게재 전 사업자등록 서류 확인)
OFFICIAL_SOURCE_CHANNELS = {"platform"}


# ---------------------------------------------------------------------------
# 비밀값·설정 읽기
# ---------------------------------------------------------------------------
_dotenv_loaded = False


def _load_dotenv_once() -> None:
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # 선택 의존성
        return
    load_dotenv(env_path, override=False)


def get_secret(name: str) -> str | None:
    """비밀값을 읽는다. 값이 없으면 None. 값을 로그·화면에 출력하지 말 것."""
    if os.environ.get("APP_TEST_MODE") == "1":
        # 단위 테스트: .env·secrets.toml 의 실제 키를 절대 읽지 않는다(실수로 유료 호출 방지)
        return os.environ.get(name) or None
    _load_dotenv_once()
    value = os.environ.get(name)
    if value:
        return value
    # Streamlit 실행 중일 때만 st.secrets 를 본다 (테스트·노트북에서는 streamlit 을 import 하지 않음)
    if "streamlit" in sys.modules:
        try:
            import streamlit as st

            value = st.secrets.get(name)
        except Exception:  # secrets 파일이 없으면 예외가 난다
            value = None
        if value:
            return str(value)
    return None


def get_setting(name: str, default: str) -> str:
    value = get_secret(name)
    return value if value else default


def get_int_setting(name: str, default: int) -> int:
    raw = get_secret(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def model_id() -> str:
    return get_setting("MODEL_ID", DEFAULT_MODEL_ID)


def session_call_limit() -> int:
    return get_int_setting("SESSION_CALL_LIMIT", DEFAULT_SESSION_CALL_LIMIT)


def daily_call_limit() -> int:
    return get_int_setting("DAILY_CALL_LIMIT", DEFAULT_DAILY_CALL_LIMIT)
