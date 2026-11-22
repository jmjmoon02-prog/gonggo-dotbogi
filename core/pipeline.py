"""처리 흐름 한 곳: 마스킹 → AI 추출 → 사실 확인 → 규칙 엔진.

화면(app.py)과 검증 노트북이 같은 함수를 쓴다.
- extractor: (마스킹된 텍스트, 출처 채널, 회차) → Extraction. 3단계에서 OpenAI 추출기를 붙인다.
- fact_checker: (Extraction, 사업자번호 목록, 이전 Facts) → Facts. 4단계에서 공공 API 를 붙인다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from .masking import BusinessNumber, Masker
from .rules_engine import RuleBook, Verdict, judge
from .schema import Extraction, Facts

KST = timezone(timedelta(hours=9))
REPLY_HEADER = "[구인자 답변]"


class Extractor(Protocol):
    name: str

    def __call__(self, masked_text: str, source_channel: str, round_no: int) -> Extraction: ...


FactChecker = Callable[[Extraction, list[BusinessNumber], Facts | None], Facts]


class ExtractionUnavailable(RuntimeError):
    """AI 추출을 할 수 없을 때. 메시지는 화면에 그대로 안내한다.

    kind: quota(OpenAI 한도·크레딧 소진) / limit(앱 호출 상한) / config(키 없음·키 오류) / error(그 밖)
    quota·limit·config 이면 화면이 '샘플 결과 보기'(미리 저장한 결과)로 대체 경로를 연다.
    """

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


@dataclass
class RoundResult:
    round_no: int
    source_channel: str
    masked_text: str  # 이번 회차까지 누적된 마스킹 텍스트 (AI 에 보낸 그대로)
    mask_counts: dict[str, int]
    business_numbers: list[BusinessNumber]
    extraction: Extraction
    facts: Facts
    verdict: Verdict
    extractor_name: str
    usage: dict | None = None  # AI 토큰 사용량 (비용 측정용)
    created_at: str = field(default_factory=lambda: datetime.now(KST).isoformat(timespec="seconds"))


def _merge_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def analyze(
    raw_text: str,
    source_channel: str,
    masker: Masker,
    extractor: Extractor,
    fact_checker: FactChecker | None = None,
    previous: RoundResult | None = None,
    rulebook: RuleBook | None = None,
) -> RoundResult:
    """1회차: raw_text = 공고 원문. 2회차: raw_text = 구인자 답변, previous = 1회차 결과."""
    masked = masker.mask(raw_text)
    if previous is None:
        round_no = 1
        masked_text = masked.masked_text.strip()
        counts = masked.counts
        biz = list(masked.business_numbers)
    else:
        round_no = previous.round_no + 1
        masked_text = f"{previous.masked_text}\n\n{REPLY_HEADER}\n{masked.masked_text.strip()}"
        counts = _merge_counts(previous.mask_counts, masked.counts)
        biz = list(previous.business_numbers) + [b for b in masked.business_numbers if b not in previous.business_numbers]

    extraction = extractor(masked_text, source_channel, round_no)
    prior_facts = previous.facts if previous else None
    facts = fact_checker(extraction, biz, prior_facts) if fact_checker else (prior_facts or Facts())
    verdict = judge(extraction, masked_text, source_channel, facts=facts, business_numbers=biz, rulebook=rulebook)
    return RoundResult(
        round_no=round_no,
        source_channel=source_channel,
        masked_text=masked_text,
        mask_counts=counts,
        business_numbers=biz,
        extraction=extraction,
        facts=facts,
        verdict=verdict,
        extractor_name=getattr(extractor, "name", type(extractor).__name__),
        usage=getattr(extractor, "last_usage", None),
    )


class CachedSampleExtractor:
    """AI 를 부를 수 없을 때(사용량 초과 등) 데모 샘플에 한해 미리 저장한 추출 결과를 쓴다."""

    def __init__(self, sample_id: str):
        self.sample_id = sample_id
        self.name = "저장된 샘플 결과"

    def __call__(self, masked_text: str, source_channel: str, round_no: int) -> Extraction:
        from .samples import cached_extraction

        ex, label = cached_extraction(self.sample_id, round_no)
        if ex is None:
            raise ExtractionUnavailable(f"샘플 '{self.sample_id}' 의 {round_no}회차 저장 결과가 없습니다.")
        self.name = label
        return ex


class FixtureExtractor:
    """개발 전용: 샘플별로 사람이 적어 둔 고정 추출값을 돌려준다(AI 호출 없음)."""

    name = "dev-fixture"

    def __init__(self, sample_id: str):
        self.sample_id = sample_id

    def __call__(self, masked_text: str, source_channel: str, round_no: int) -> Extraction:
        from .samples import dev_fixture

        ex = dev_fixture(self.sample_id, round_no)
        if ex is None:
            raise ExtractionUnavailable(f"샘플 '{self.sample_id}' 의 {round_no}회차 고정 추출값이 없습니다.")
        return ex
