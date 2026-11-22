"""데모 샘플·테스트셋·개발용 고정 추출값 불러오기."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from . import config
from .schema import Extraction

GRADES = ("red", "orange", "yellow", "white", "green")
FLAGGED_GRADES = {"red", "orange", "yellow"}  # '위험 쪽으로 표시'로 보는 등급 (오탐·탐지 계산용)


@dataclass(frozen=True)
class Sample:
    id: str
    title: str
    source_channel: str
    expected_grade: str
    text: str
    reply: str | None
    reply_expected_grade: str | None


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_samples() -> tuple[Sample, ...]:
    raw = _read_yaml(config.SAMPLES_DIR / "samples.yaml")
    return tuple(
        Sample(
            id=s["id"],
            title=s["title"],
            source_channel=s["source_channel"],
            expected_grade=s["expected_grade"],
            text=s["text"].strip(),
            reply=(s.get("reply") or "").strip() or None,
            reply_expected_grade=s.get("reply_expected_grade"),
        )
        for s in raw
    )


def get_sample(sample_id: str) -> Sample | None:
    return next((s for s in load_samples() if s.id == sample_id), None)


# ---------------------------------------------------------------------------
# 개발용 고정 추출값 (AI 대신)
# ---------------------------------------------------------------------------
_EMPTY_EXTRACTION = {
    "company": {"name": None, "name_quote": None, "region": None, "claims_known_brand": False,
                "brand_name": None, "brand_quote": None},
    "job": {"title": None, "duties_summary": None, "duty_clarity": "unknown", "work_location": None,
            "overseas": False, "overseas_country": None, "overseas_perks": [], "overseas_quote": None},
    "pay": {"amount_text": None, "unit": "unknown", "amount_krw": None, "hours_per_unit": None,
            "same_day_pay": False, "quote": None},
    "contact": {"channels": [], "moves_to_messenger": False, "quote": None},
    "requirements": {"gender_restriction": None, "age_restriction": None, "quote": None},
    "value_flow": {"worker_pays": [], "worker_receives": [], "passes_through_worker": [],
                   "required_actions": [], "control_loss": [], "hiring_process": None},
    "signals": [],
    "axis_violations": [],
    "injection": {"detected": False, "quote": None},
    "other_anomalies": [],
    "missing_info": [],
    "follow_up_questions": [],
}


def extraction_from_partial(partial: dict | None) -> Extraction:
    """빠진 필드를 기본값으로 채워 Extraction 을 만든다."""
    data = copy.deepcopy(_EMPTY_EXTRACTION)
    for key, value in (partial or {}).items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value
    return Extraction.model_validate(data)


@lru_cache(maxsize=1)
def _dev_fixture_data() -> dict:
    return _read_yaml(config.SAMPLES_DIR / "dev_fixtures.yaml") or {}


def dev_fixture(sample_id: str, round_no: int) -> Extraction | None:
    entry = _dev_fixture_data().get(sample_id) or {}
    partial = entry.get(f"round{round_no}")
    return extraction_from_partial(partial) if partial is not None else None


# ---------------------------------------------------------------------------
# 미리 저장한 실제 AI 추출 결과 (AI 사용량 초과·장애 시 '샘플 결과 화면'용)
# 마감 전에 scripts/smoke_openai.py --save-cache 로 실제 호출 결과를 저장한다.
# ---------------------------------------------------------------------------
CACHE_FILE = config.SAMPLES_DIR / "cached_extractions.json"


@lru_cache(maxsize=1)
def _cache_data() -> dict:
    if not CACHE_FILE.exists():
        return {}
    return json.loads(CACHE_FILE.read_text(encoding="utf-8"))


def cached_extraction(sample_id: str, round_no: int) -> tuple[Extraction | None, str]:
    """(추출값, 출처 설명). 저장된 실제 AI 결과가 있으면 그것, 없으면 사람이 적은 예시 추출값."""
    data = _cache_data()
    entry = ((data.get("items") or {}).get(sample_id) or {}).get(f"round{round_no}")
    if entry:
        meta = data.get("meta") or {}
        label = f"저장된 AI 결과(openai:{meta.get('model', '?')}, {meta.get('recorded_at', '?')} 실제 호출)"
        return Extraction.model_validate(entry), label
    ex = dev_fixture(sample_id, round_no)
    return ex, "예시 추출값(사람 작성, AI 호출 없음)"


def save_cached_extractions(items: dict[str, dict[str, Extraction]], model: str, recorded_at: str) -> Path:
    payload = {
        "meta": {"model": model, "recorded_at": recorded_at,
                 "note": "데모 샘플(가상 데이터)을 실제 AI 로 추출한 결과. AI 사용량 초과·장애 시 샘플 결과 화면에 쓴다."},
        "items": {sid: {k: ex.model_dump() for k, ex in rounds.items()} for sid, rounds in items.items()},
    }
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    _cache_data.cache_clear()
    return CACHE_FILE


# ---------------------------------------------------------------------------
# 테스트셋
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_testset() -> dict:
    return _read_yaml(config.TESTSET_DIR / "testset.yaml")


def validate_testset(data: dict, rule_ids: set[str]) -> list[str]:
    errors: list[str] = []
    groups = (data.get("meta") or {}).get("groups") or {}
    seen: set[str] = set()
    for it in data.get("items", []):
        iid = it.get("id", "?")
        if iid in seen:
            errors.append(f"{iid}: ID 중복")
        seen.add(iid)
        for f in ("group", "class", "source_channel", "text", "expected_grade", "acceptable_grades", "expected_rules"):
            if f not in it:
                errors.append(f"{iid}: 필드 없음 '{f}'")
        if it.get("group") not in groups:
            errors.append(f"{iid}: 알 수 없는 group {it.get('group')}")
        if it.get("class") not in {"scam", "normal"}:
            errors.append(f"{iid}: class 값 오류")
        if it.get("source_channel") not in config.SOURCE_CHANNELS:
            errors.append(f"{iid}: source_channel 값 오류")
        if it.get("expected_grade") not in GRADES:
            errors.append(f"{iid}: expected_grade 값 오류")
        if it.get("expected_grade") not in (it.get("acceptable_grades") or []):
            errors.append(f"{iid}: expected_grade 가 acceptable_grades 에 없음")
        for r in it.get("expected_rules") or []:
            if r not in rule_ids:
                errors.append(f"{iid}: 규칙 ID '{r}' 없음")
        if it.get("class") == "normal" and set(it.get("acceptable_grades") or []) & FLAGGED_GRADES:
            errors.append(f"{iid}: 정상 공고의 허용 등급에 위험 쪽 등급이 있음")
    return errors
