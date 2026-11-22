"""AI 추출 결과·사실 확인 결과의 데이터 형식.

- Extraction: AI 추출 단계(core/extract.py, 3단계)가 채운다. 규칙 엔진은 이 형식만 읽는다.
  OpenAI 구조화 출력(JSON 스키마)으로 형식을 강제할 예정이며, 신호 ID 목록은 rules.yaml 에서 만들어
  스키마에 넣는다(규칙을 데이터로 유지하기 위해 여기서는 str 로 둔다).
- Facts: 공공 API 조회(core/verify_apis.py, 4단계)가 채운다. 기본값은 모두 '조회 안 함'.

모든 인용(quote) 필드는 '마스킹된 원문'에서 그대로 옮긴 문장이어야 한다. 규칙 엔진이 코드로 확인한다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# AI 추출 결과
# ---------------------------------------------------------------------------
ContactChannel = Literal[
    "platform_message",  # 채용 플랫폼 내 메시지·지원 버튼
    "phone_call",
    "sms",
    "kakao_personal",  # 카카오톡 개인 친구 추가
    "kakao_openchat",
    "telegram",
    "line",
    "instagram_dm",
    "other_messenger",
    "email",
    "external_link",  # 외부 사이트·앱 링크
    "in_person",
    "unknown",
]

# 문자·개인 메신저·비공식 링크 (사칭 조건, E59)
UNOFFICIAL_CONTACTS = {
    "sms",
    "kakao_personal",
    "kakao_openchat",
    "telegram",
    "line",
    "instagram_dm",
    "other_messenger",
    "external_link",
}


class QuotedItem(_Strict):
    item: str = Field(description="무엇인지 짧게")
    quote: str = Field(description="근거 문장, 원문 그대로")


class Company(_Strict):
    name: str | None = Field(description="공고에 적힌 업체명(상호). 없으면 null")
    name_quote: str | None
    region: str | None = Field(description="업체·근무지 지역(시도·시군구), 원문 표기 그대로")
    claims_known_brand: bool = Field(description="유명 브랜드·대기업·유명 쇼핑몰 이름을 내세우는지")
    brand_name: str | None
    brand_quote: str | None


class Job(_Strict):
    title: str | None
    duties_summary: str | None
    duty_clarity: Literal["clear", "vague", "unknown"]
    work_location: str | None
    overseas: bool
    overseas_country: str | None
    overseas_perks: list[Literal["flight", "lodging", "no_visa", "high_pay"]]
    overseas_quote: str | None


class Pay(_Strict):
    amount_text: str | None = Field(description="급여 표기 원문 그대로")
    unit: Literal["hour", "day", "week", "month", "per_task", "unknown"]
    amount_krw: int | None = Field(description="원 단위 숫자. '15만'→150000")
    hours_per_unit: float | None = Field(description="그 급여 단위당 근무시간. 모르면 null")
    same_day_pay: bool
    quote: str | None


class Contact(_Strict):
    channels: list[ContactChannel]
    moves_to_messenger: bool
    quote: str | None


class Requirements(_Strict):
    gender_restriction: str | None
    age_restriction: str | None
    quote: str | None


class ValueFlow(_Strict):
    """정상 고용은 가치가 구인자 → 근로자(임금)로 흐른다. 반대 흐름을 찾기 위한 구조화."""

    worker_pays: list[QuotedItem] = Field(description="근로자가 내야 하는 것(돈·정보·명의 등)")
    worker_receives: list[QuotedItem] = Field(description="근로자가 받는 것")
    passes_through_worker: list[QuotedItem] = Field(description="근로자를 거쳐 가는 돈·물건·카드·계정")
    required_actions: list[QuotedItem] = Field(description="요구하는 행동")
    control_loss: list[QuotedItem] = Field(description="근로자가 잃는 통제(여권·휴대폰·이동·연락)")
    hiring_process: str | None = Field(description="연락·채용 방식 요약")


class SignalCandidate(_Strict):
    signal_id: str = Field(description="rules.yaml 의 규칙 ID (AI 탐지 대상만)")
    quote: str = Field(description="근거 문장, 원문 그대로")
    explanation: str


class AxisViolation(_Strict):
    axis: Literal["A", "B", "C", "D", "E", "F"]
    quote: str
    explanation: str


class Injection(_Strict):
    detected: bool = Field(description="공고 본문에 AI·판정기에게 판정을 지시하는 문장이 있는지")
    quote: str | None


class Anomaly(_Strict):
    description: str
    quote: str | None


class Extraction(_Strict):
    company: Company
    job: Job
    pay: Pay
    contact: Contact
    requirements: Requirements
    value_flow: ValueFlow
    signals: list[SignalCandidate]
    axis_violations: list[AxisViolation]
    injection: Injection
    other_anomalies: list[Anomaly] = Field(description="기타 이상 신호. 설명만 하고 판정에는 쓰지 않는다")
    missing_info: list[str] = Field(description="지원 전에 확인해야 할 빠진 정보")
    follow_up_questions: list[str] = Field(
        description="이 공고에 맞춰 구인자에게 물어볼 확인 질문(최대 3개). 위험 신호를 드러내게 하는 질문, 개인정보 요구 금지"
    )


# ---------------------------------------------------------------------------
# 공공 API 사실 확인 결과 (4단계에서 채움)
# ---------------------------------------------------------------------------
class NtsResult(BaseModel):
    """국세청 사업자 상태 (E27)."""

    status: Literal["active", "suspended", "closed", "not_registered", "error", "not_checked"] = "not_checked"
    business_number: str | None = None
    checked_at: str | None = None
    message: str | None = None


class NpsCandidate(BaseModel):
    name: str
    biz_prefix6: str | None = None
    members: int | None = None
    industry: str | None = None
    address: str | None = None
    status: str | None = None


class NpsResult(BaseModel):
    """국민연금 가입 사업장 (E52). 0건은 '확인 불가'(위험 아님)."""

    match: Literal["single", "multiple", "none", "error", "not_checked"] = "not_checked"
    candidates: list[NpsCandidate] = Field(default_factory=list)
    checked_at: str | None = None
    message: str | None = None


class WorknetResult(BaseModel):
    """워크넷 공식 공고 대조 (E53). API 가 죽으면 disabled/error 로 두고 판정은 계속."""

    match: Literal["match", "mismatch", "none", "error", "disabled", "not_checked"] = "not_checked"
    detail: str | None = None
    url: str | None = None
    checked_at: str | None = None


class Facts(BaseModel):
    nts: NtsResult = Field(default_factory=NtsResult)
    nps: NpsResult = Field(default_factory=NpsResult)
    worknet: WorknetResult = Field(default_factory=WorknetResult)
    industry_mismatch: bool | None = None  # M4, 4단계에서 계산 방식 확정
