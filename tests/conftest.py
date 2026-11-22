"""테스트 공통: app/ 를 import 경로에 넣고, 손으로 만든 추출값(가상 데이터) 생성기를 제공한다.

API 호출 없음. 모든 공고 문장은 가상으로 지어낸 것이다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 실제 키(.env / secrets.toml)를 읽지 않게 한다. 테스트에서 OpenAI 를 실제로 호출하는 일은 없다.
os.environ["APP_TEST_MODE"] = "1"
for _k in ("OPENAI_API_KEY", "DATA_GO_KR_SERVICE_KEY", "WORK24_AUTH_KEY", "HF_TOKEN", "DEV_FIXTURES"):
    os.environ.pop(_k, None)

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.schema import (  # noqa: E402
    AxisViolation,
    Company,
    Contact,
    Extraction,
    Injection,
    Job,
    Pay,
    Requirements,
    SignalCandidate,
    ValueFlow,
)


def sig(signal_id: str, quote: str, explanation: str = "테스트") -> SignalCandidate:
    return SignalCandidate(signal_id=signal_id, quote=quote, explanation=explanation)


def axis(axis_id: str, quote: str, explanation: str = "테스트") -> AxisViolation:
    return AxisViolation(axis=axis_id, quote=quote, explanation=explanation)


def make_extraction(
    *,
    company_name: str | None = None,
    claims_known_brand: bool = False,
    brand_name: str | None = None,
    brand_quote: str | None = None,
    pay_unit: str = "unknown",
    pay_amount: int | None = None,
    pay_hours: float | None = None,
    pay_quote: str | None = None,
    channels: list[str] | None = None,
    overseas: bool = False,
    overseas_perks: list[str] | None = None,
    overseas_quote: str | None = None,
    signals: list[SignalCandidate] | None = None,
    axes: list[AxisViolation] | None = None,
    injection_quote: str | None = None,
    missing_info: list[str] | None = None,
) -> Extraction:
    return Extraction(
        company=Company(
            name=company_name,
            name_quote=company_name,
            name_missing=company_name is None,
            region=None,
            claims_known_brand=claims_known_brand,
            brand_name=brand_name,
            brand_quote=brand_quote,
        ),
        job=Job(
            title=None,
            duties_summary=None,
            duty_clarity="unknown",
            work_location=None,
            overseas=overseas,
            overseas_country=None,
            overseas_perks=overseas_perks or [],
            overseas_quote=overseas_quote,
        ),
        pay=Pay(
            amount_text=pay_quote,
            unit=pay_unit,
            amount_krw=pay_amount,
            hours_per_unit=pay_hours,
            same_day_pay=False,
            quote=pay_quote,
        ),
        contact=Contact(channels=channels or [], moves_to_messenger=False, quote=None),
        requirements=Requirements(gender_restriction=None, age_restriction=None, quote=None),
        value_flow=ValueFlow(
            worker_pays=[],
            worker_receives=[],
            passes_through_worker=[],
            required_actions=[],
            control_loss=[],
            hiring_process=None,
        ),
        signals=signals or [],
        axis_violations=axes or [],
        injection=Injection(detected=injection_quote is not None, quote=injection_quote),
        other_anomalies=[],
        missing_info=missing_info or [],
        follow_up_questions=[],
    )
