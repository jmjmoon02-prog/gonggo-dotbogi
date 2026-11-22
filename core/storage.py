"""사례 저장 (학습 고리): 사용자가 동의한 경우에만, 개인정보를 가린 사례를 비공개 Hugging Face Dataset 에 저장한다.

- 저장하는 것: 마스킹된 공고·답변 텍스트(사업자등록번호도 다시 가림), AI 추출 결과(구조화), 판정 요약, 저장 시각, 계기
- 저장하지 않는 것: 원문, 이미지, 업체 조회 결과(국세청·국민연금 등), 사업자등록번호, 접속 정보
- 보관: 저장일부터 RETENTION_DAYS 일. 기한(expires_at)이 지난 사례는 검토 노트북(rule_review.ipynb)이 지운다.
- 저장된 사례는 사람이 공식 근거를 확인해 승인해야만 규칙 후보가 된다. 피드백만으로 규칙은 바뀌지 않는다.

Hugging Face 사용법(huggingface_hub 2.4.0, 설치본 시그니처와 공식 문서 2026-11-23 확인):
HfApi().upload_file(path_or_fileobj=bytes, path_in_repo=..., repo_id=..., repo_type="dataset", token=..., commit_message=...)
→ 호출 1번 = 커밋 1개. 사례는 드물게(동의·버튼) 생기므로 건별 커밋으로 충분하다.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from . import config

KST = timezone(timedelta(hours=9))
RETENTION_DAYS = 90
MAX_SAVES_PER_SESSION = 5
CASE_DIR_IN_REPO = "cases"
LOCAL_CASE_DIR = config.APP_DIR / "data" / "cases_local"  # 개발용, Git 제외
_BIZ_NO = re.compile(r"(?<!\d)\d{3}\s?-\s?\d{2}\s?-\s?\d{5}(?!\d)")

TRIGGERS = {
    "feedback_wrong": "판정이 틀렸어요",
    "feedback_scam": "실제로 사기였어요",
    "novel_suspect": "신종 의심 사례",
    "synthetic_eval": "평가용 가상 사례(검증 노트북의 '유형 하나 빼기'에서 신종 의심으로 판정된 테스트셋 항목)",
}

SAVED_ITEMS = [
    "개인정보를 가린 공고·답변 텍스트 (전화·계좌·이름 등은 이미 [토큰]으로 가려진 상태, 사업자등록번호도 가림)",
    "AI가 뽑은 구조화 결과 (업체·급여·연락 경로·돈의 흐름·신호 후보)",
    "판정 결과 (등급·걸린 규칙·이유)와 저장 시각",
]
NOT_SAVED_ITEMS = ["입력 원문과 이미지", "업체 조회 결과(국세청·국민연금)", "사업자등록번호", "IP 등 접속 정보"]


def retention_notice() -> str:
    return (f"비공개 저장소에 저장되며, 저장일부터 {RETENTION_DAYS}일이 지나면 삭제합니다. "
            "규칙 검토(사람이 공식 근거를 확인해 승인)에만 쓰며, 피드백만으로 규칙이 바뀌지는 않습니다.")


def _remask(text: str) -> str:
    return _BIZ_NO.sub("[사업자번호]", text)


def build_case(rounds: list, trigger: str, now: datetime | None = None) -> dict:
    """RoundResult 목록 → 저장할 사례(dict). 업체 조회 결과(facts)·사업자번호는 넣지 않는다."""
    if trigger not in TRIGGERS:
        raise ValueError(f"알 수 없는 저장 계기: {trigger}")
    now = now or datetime.now(KST)
    last = rounds[-1]
    v = last.verdict
    extraction_json = _remask(json.dumps(last.extraction.model_dump(), ensure_ascii=False))
    return {
        "schema_version": 1,
        "case_id": uuid.uuid4().hex[:12],
        "trigger": trigger,
        "trigger_label": TRIGGERS[trigger],
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(days=RETENTION_DAYS)).date().isoformat(),
        "source_channel": last.source_channel,
        "rounds": len(rounds),
        "masked_text": _remask(last.masked_text),
        "extraction": json.loads(extraction_json),
        "verdict": {
            "grade": v.grade,
            "label": v.label,
            "novel_suspect": v.novel_suspect,
            "matched_ids": v.matched_ids,
            "candidate_rule_ids": [h.rule_id for h in v.candidate_hits],
            "reasons": [_remask(r) for r in v.reasons],
            "rules_version": v.rules_version,
        },
        "history": [{"round": r.round_no, "grade": r.verdict.grade} for r in rounds],
        "extractor": last.extractor_name,
        "consent": True,
    }


class CaseStore(Protocol):
    name: str

    def save(self, case: dict) -> str: ...


class HFDatasetStore:
    """비공개 Hugging Face Dataset 저장소(토큰은 Secrets)."""

    name = "Hugging Face Dataset(비공개)"

    def __init__(self, token: str, repo_id: str, api=None):
        if api is None:
            from huggingface_hub import HfApi

            api = HfApi()
        self.api, self.token, self.repo_id = api, token, repo_id

    def save(self, case: dict) -> str:
        day = case["created_at"][:10]
        path = f"{CASE_DIR_IN_REPO}/{day}/{case['case_id']}.json"
        self.api.upload_file(
            path_or_fileobj=json.dumps(case, ensure_ascii=False, indent=1).encode("utf-8"),
            path_in_repo=path,
            repo_id=self.repo_id,
            repo_type="dataset",
            token=self.token,
            commit_message=f"case {case['case_id']} ({case['trigger']})",
        )
        return path


class LocalCaseStore:
    """개발 모드 전용(토큰 없을 때). app/data/cases_local/ 은 Git 제외."""

    name = "로컬 폴더(개발용)"

    def __init__(self, root: Path | None = None):
        self.root = root

    @property
    def _dir(self) -> Path:
        return self.root or LOCAL_CASE_DIR

    def save(self, case: dict) -> str:
        d = self._dir / case["created_at"][:10]
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{case['case_id']}.json"
        p.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            return str(p.relative_to(config.APP_DIR))
        except ValueError:
            return str(p)


def get_store(dev_mode: bool = False) -> CaseStore | None:
    token, repo = config.get_secret("HF_TOKEN"), config.get_secret("HF_DATASET_REPO")
    if token and repo:
        return HFDatasetStore(token, repo)
    if dev_mode:
        return LocalCaseStore()
    return None


def expired(case: dict, today: datetime | None = None) -> bool:
    today = today or datetime.now(KST)
    return case.get("expires_at", "9999-12-31") < today.date().isoformat()
