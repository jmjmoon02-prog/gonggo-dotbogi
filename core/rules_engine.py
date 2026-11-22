"""규칙 엔진: rules.yaml + AI 추출 결과 + 공공 API 결과 → 판정 등급.

AI 는 추출·설명만 하고, 등급은 이 코드가 정한다(같은 입력이면 같은 결과).

등급 결정 순서 (판정 규칙 v2 + 신종 수법 대응 원칙 6축, rules/rules.yaml)
  1. H 또는 원칙 축 A~D 위반 → 🔴 위험 (H 없이 축만이면 '신종 의심')
  2. 사칭 조건 → 🟠 사칭 의심
  3. M, 또는 약한 신호 2개 이상, 또는 신뢰 신호 없이 축 E·F 위반 → 🟡 주의
  4. 신뢰 신호(T) + H·M 없음 + 약한 신호 1개 이하 → 🟢 낮은 위험
  5. 그 밖(정보 부족·동명 후보·비공식 채널) → ⚪ 확인 필요
인용 검증: AI 가 낸 근거 문장이 마스킹된 원문에 없으면 그 신호를 한 단계 낮춘다
  (H→중간, M→약한, S→반영 안 함 / 축 A~D→🟡, 축 E·F→반영 안 함).
AI 는 신뢰 신호(T)·코드 전용 신호를 만들 수 없다(조작 방지).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import config
from .masking import quote_in_text
from .schema import UNOFFICIAL_CONTACTS, Extraction, Facts, Pay

VALID_TIERS = {"H", "M", "I", "S", "T", "X", "L"}
VALID_AXES = {"A", "B", "C", "D", "E", "F"}
VALID_STATUS = {"active", "candidate"}
REQUIRED_RULE_FIELDS = (
    "id", "tier", "axis", "detection", "name", "description", "examples", "check_question",
    "legal_note", "evidence_ids", "version", "status",
)

# 신호 강도: red > yellow > yellow_untrusted(신뢰 신호 없을 때만 🟡) > weak > none
LEVEL_RANK = {"red": 4, "yellow": 3, "yellow_untrusted": 2, "weak": 1, "none": 0}
_BASE_LEVEL = {"H": "red", "M": "yellow", "X": "yellow", "S": "weak"}
_DEMOTE = {"red": "yellow", "yellow": "weak", "yellow_untrusted": "none", "weak": "none", "none": "none"}
_CONTACT_ORDER = ["police", "fss", "cyber_365", "molit_logistics", "kotra"]

# 판정기 조종 문장 (코드 보조 탐지, 좁게 잡는다 — 'AI 데이터 라벨링' 같은 정상 업무 오탐 방지)
_INJECTION_PATTERNS = [
    re.compile(r"(이전|앞의|위의?|기존|모든)\s*(지시|명령|지침|프롬프트|규칙)[^\n]{0,15}(무시|잊)"),
    re.compile(r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above)\s+(instructions?|prompts?)", re.I),
    re.compile(r"(시스템\s*프롬프트|system\s*prompt)", re.I),
    re.compile(
        r"이\s*(공고|글|게시물|메시지|문자)[은는를이가]?[^\n]{0,25}"
        r"(정상|문제\s*없|위험\s*(하지)?\s*않|위험\s*(이|이\s*)?없|사기\s*(가|이)?\s*아니|낮은\s*위험)[^\n]{0,15}"
        r"(판정|판단|분류|평가|답변|출력)"
    ),
    re.compile(
        r"(판정|분류|등급)[^\n]{0,10}(낮은\s*위험|정상|초록|green)[^\n]{0,6}(으로|로)\s*"
        r"(하라|해라|할\s*것|하세요|해\s*주세요|하십시오|출력)",
        re.I,
    ),
]


# ---------------------------------------------------------------------------
# 규칙 파일
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    id: str
    tier: str
    axis: str | None
    detection: str
    name: str
    description: str
    examples: tuple[str, ...]
    check_question: str | None
    guidance: str | None
    legal_note: str | None
    report_to: tuple[str, ...]
    extra_report_if_keywords: dict[str, tuple[str, ...]]
    evidence_ids: tuple[str, ...]
    version: str
    status: str
    blocks_green: bool = False  # 이 신호가 있으면 🟢 낮은 위험을 주지 않는다

    @property
    def ai_detectable(self) -> bool:
        return "ai" in self.detection.split("+")


@dataclass(frozen=True)
class Axis:
    id: str
    severity: str
    name: str
    principle: str
    check_question: str
    evidence_ids: tuple[str, ...]
    evidence_note: str | None = None  # 원문 인용이 아니라 사례에서 도출한 원칙일 때


@dataclass(frozen=True)
class RuleBook:
    meta: dict
    grades: dict
    thresholds: dict
    evidence: dict
    contacts: dict
    principles: list
    general_questions: list
    rules: dict[str, Rule]
    axes: dict[str, Axis]
    fact_questions: dict = field(default_factory=dict)
    industry_mismatch: dict = field(default_factory=dict)

    @property
    def version(self) -> str:
        return str(self.meta.get("version", "?"))

    def active_rules(self) -> list[Rule]:
        return [r for r in self.rules.values() if r.status == "active"]

    def ai_rules(self, include_candidates: bool = False) -> list[Rule]:
        ok = {"active", "candidate"} if include_candidates else {"active"}
        return [r for r in self.rules.values() if r.ai_detectable and r.status in ok]

    def evidence_link(self, eid: str) -> dict | None:
        return self.evidence.get(eid)


def _parse_rulebook(data: dict) -> RuleBook:
    rules = {}
    for raw in data.get("rules", []):
        rules[raw["id"]] = Rule(
            id=raw["id"],
            tier=raw["tier"],
            axis=raw.get("axis"),
            detection=raw.get("detection", "ai"),
            name=raw["name"],
            description=raw["description"],
            examples=tuple(raw.get("examples") or ()),
            check_question=raw.get("check_question"),
            guidance=raw.get("guidance"),
            legal_note=raw.get("legal_note"),
            report_to=tuple(raw.get("report_to") or ()),
            extra_report_if_keywords={k: tuple(v) for k, v in (raw.get("extra_report_if_keywords") or {}).items()},
            evidence_ids=tuple(raw.get("evidence_ids") or ()),
            version=str(raw.get("version")),
            status=raw.get("status", "active"),
            blocks_green=bool(raw.get("blocks_green", False)),
        )
    axes = {
        a["id"]: Axis(
            id=a["id"],
            severity=a["severity"],
            name=a["name"],
            principle=a["principle"],
            check_question=a["check_question"],
            evidence_ids=tuple(a.get("evidence_ids") or ()),
            evidence_note=a.get("evidence_note"),
        )
        for a in data.get("axes", [])
    }
    return RuleBook(
        meta=data.get("meta", {}),
        grades=data.get("grades", {}),
        thresholds=data.get("thresholds", {}),
        evidence=data.get("evidence", {}),
        contacts=data.get("contacts", {}),
        principles=data.get("principles", []),
        general_questions=data.get("general_questions", []),
        rules=rules,
        axes=axes,
        fact_questions=data.get("fact_questions", {}) or {},
        industry_mismatch=data.get("industry_mismatch", {}) or {},
    )


def validate_rules_data(data: dict) -> list[str]:
    """rules.yaml 형식 점검. 문제 목록을 돌려준다(빈 목록이면 통과). 학습 고리 회귀 시험에서도 쓴다."""
    errors: list[str] = []
    evidence = data.get("evidence", {}) or {}
    contacts = data.get("contacts", {}) or {}
    seen: set[str] = set()
    for raw in data.get("rules", []):
        rid = raw.get("id", "?")
        for f in REQUIRED_RULE_FIELDS:
            if f not in raw:
                errors.append(f"{rid}: 필드 없음 '{f}'")
        if rid in seen:
            errors.append(f"{rid}: ID 중복")
        seen.add(rid)
        if raw.get("tier") not in VALID_TIERS:
            errors.append(f"{rid}: tier 값 오류 {raw.get('tier')}")
        if raw.get("axis") is not None and raw.get("axis") not in VALID_AXES:
            errors.append(f"{rid}: axis 값 오류 {raw.get('axis')}")
        if raw.get("status") not in VALID_STATUS:
            errors.append(f"{rid}: status 값 오류 {raw.get('status')}")
        det = str(raw.get("detection", ""))
        if not set(det.split("+")) <= {"ai", "code"}:
            errors.append(f"{rid}: detection 값 오류 {det}")
        if raw.get("status") == "active" and raw.get("tier") in {"H", "M", "I", "S", "L"} and not raw.get("evidence_ids"):
            errors.append(f"{rid}: active 규칙인데 근거 ID 없음")
        for eid in raw.get("evidence_ids") or []:
            if eid not in evidence:
                errors.append(f"{rid}: 근거 ID '{eid}'가 evidence 목록에 없음")
        for c in raw.get("report_to") or []:
            if c not in contacts:
                errors.append(f"{rid}: 신고처 '{c}'가 contacts 에 없음")
        for c in (raw.get("extra_report_if_keywords") or {}):
            if c not in contacts:
                errors.append(f"{rid}: 신고처 '{c}'가 contacts 에 없음")
    axis_ids = {a.get("id") for a in data.get("axes", [])}
    if axis_ids != VALID_AXES:
        errors.append(f"axes 는 A~F 6개여야 함: {sorted(axis_ids)}")
    for a in data.get("axes", []):
        if a.get("severity") not in {"red", "yellow"}:
            errors.append(f"축 {a.get('id')}: severity 값 오류")
        for eid in a.get("evidence_ids") or []:
            if eid not in evidence:
                errors.append(f"축 {a.get('id')}: 근거 ID '{eid}' 없음")
    for c in contacts.values():
        for eid in c.get("evidence_ids") or []:
            if eid not in evidence:
                errors.append(f"신고처 {c.get('name')}: 근거 ID '{eid}' 없음")
    for g in ("red", "orange", "yellow", "white", "green"):
        if g not in (data.get("grades") or {}):
            errors.append(f"grades 에 '{g}' 없음")
    return errors


@lru_cache(maxsize=4)
def _load_cached(path_str: str, mtime: float) -> RuleBook:
    data = yaml.safe_load(Path(path_str).read_text(encoding="utf-8"))
    errors = validate_rules_data(data)
    if errors:
        raise ValueError("rules.yaml 형식 오류:\n- " + "\n- ".join(errors))
    return _parse_rulebook(data)


def load_rules(path: str | Path | None = None) -> RuleBook:
    p = Path(path) if path else config.RULES_PATH
    return _load_cached(str(p), p.stat().st_mtime)


def rulebook_from_dict(data: dict) -> RuleBook:
    """테스트·'유형 하나 빼기' 실험용: 메모리의 규칙 데이터로 RuleBook 생성."""
    errors = validate_rules_data(data)
    if errors:
        raise ValueError("규칙 데이터 형식 오류:\n- " + "\n- ".join(errors))
    return _parse_rulebook(data)


# ---------------------------------------------------------------------------
# 판정 결과
# ---------------------------------------------------------------------------
@dataclass
class Hit:
    rule_id: str  # 규칙 ID 또는 'AX_B' 같은 축 ID
    kind: str  # rule | axis
    tier: str  # H/M/S/I/T/X/L 또는 AX
    name: str
    base_level: str
    level: str  # 인용 검증 반영 후
    quote: str | None
    quote_verified: bool | None  # None = 코드가 계산한 신호(인용 불필요)
    source: str  # ai | code
    explanation: str | None = None
    evidence_ids: tuple[str, ...] = ()
    guidance: str | None = None
    legal_note: str | None = None
    check_question: str | None = None

    @property
    def demoted(self) -> bool:
        return self.level != self.base_level


@dataclass
class Verdict:
    grade: str  # red | orange | yellow | white | green
    emoji: str
    label: str
    novel_suspect: bool  # 알려진 규칙 없이 원칙 축만으로 판정(신종 의심)
    reasons: list[str]
    hits: list[Hit]  # 위험 쪽 신호 (강한 순)
    trust: list[Hit]
    impersonation: Hit | None
    anomalies: list[Hit]  # X: 판정기 조종 문장
    labor_flags: list[Hit]  # L: 근로조건 위법 가능 (사기 판정과 분리)
    candidate_hits: list[Hit]  # status: candidate 규칙 (판정 미반영, 학습 고리 검토용)
    info_needed: list[str]
    legal_notes: list[dict]
    report_contacts: list[dict]
    check_questions: list[dict]
    ignored_signal_ids: list[str]  # AI 가 냈지만 반영하지 않은 신호 ID
    hourly_wage: float | None
    rules_version: str

    @property
    def matched_ids(self) -> list[str]:
        ids = [h.rule_id for h in self.hits if h.level != "none"]
        if self.impersonation:
            ids.append(self.impersonation.rule_id)
        return ids

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 보조 계산
# ---------------------------------------------------------------------------
def hourly_wage(pay: Pay) -> tuple[float | None, bool]:
    """(시급 환산액, 근무시간을 가정했는지). 계산 불가면 (None, False)."""
    amount = pay.amount_krw
    if not amount or amount <= 0:
        return None, False
    if pay.unit == "hour":
        return float(amount), False
    hours = pay.hours_per_unit
    if pay.unit in {"day", "week"}:
        return (amount / hours, False) if hours and hours > 0 else (None, False)
    if pay.unit == "month":
        if hours and hours > 0:
            return amount / hours, False
        return amount / config.MONTHLY_STANDARD_HOURS, True  # 월 209시간 가정(가장 낮게 잡는 쪽)
    return None, False


def detect_injection(text: str) -> str | None:
    for p in _INJECTION_PATTERNS:
        m = p.search(text)
        if m:
            return m.group(0)
    return None


def _rule_hit(rule: Rule, level: str, quote: str | None, verified: bool | None, source: str,
              explanation: str | None = None, base_level: str | None = None) -> Hit:
    return Hit(
        rule_id=rule.id,
        kind="rule",
        tier=rule.tier,
        name=rule.name,
        base_level=base_level or level,
        level=level,
        quote=quote,
        quote_verified=verified,
        source=source,
        explanation=explanation,
        evidence_ids=rule.evidence_ids,
        guidance=rule.guidance,
        legal_note=rule.legal_note,
        check_question=rule.check_question,
    )


def _better(a: Hit, b: Hit) -> Hit:
    """같은 규칙이 여러 번 잡히면 더 강한(검증된) 쪽을 남긴다."""
    if LEVEL_RANK[b.level] > LEVEL_RANK[a.level]:
        return b
    if LEVEL_RANK[b.level] == LEVEL_RANK[a.level] and a.quote_verified is False and b.quote_verified:
        return b
    return a


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------
def judge(
    extraction: Extraction,
    masked_text: str,
    source_channel: str,
    facts: Facts | None = None,
    business_numbers: list | None = None,
    rulebook: RuleBook | None = None,
) -> Verdict:
    rb = rulebook or load_rules()
    facts = facts or Facts()
    th = rb.thresholds
    risk: dict[str, Hit] = {}
    candidates: dict[str, Hit] = {}
    ignored: list[str] = []

    def add(hit: Hit, status: str = "active") -> None:
        bucket = candidates if status == "candidate" else risk
        bucket[hit.rule_id] = _better(bucket[hit.rule_id], hit) if hit.rule_id in bucket else hit

    def verified(q: str | None) -> bool:
        return quote_in_text(q, masked_text)

    # 1) AI 신호 후보 (AI 탐지 대상 규칙만)
    for sc in extraction.signals:
        rule = rb.rules.get(sc.signal_id)
        if rule is None or not rule.ai_detectable or rule.tier not in _BASE_LEVEL:
            ignored.append(sc.signal_id)
            continue
        ok = verified(sc.quote)
        base = _BASE_LEVEL[rule.tier]
        add(_rule_hit(rule, base if ok else _DEMOTE[base], sc.quote, ok, "ai", sc.explanation, base), rule.status)

    # 2) 원칙 축 위반 (신종 대응)
    for av in extraction.axis_violations:
        axis = rb.axes[av.axis]
        base = "red" if axis.severity == "red" else "yellow_untrusted"
        ok = verified(av.quote)
        add(Hit(
            rule_id=f"AX_{axis.id}", kind="axis", tier="AX", name=f"원칙 {axis.id}: {axis.name}",
            base_level=base, level=base if ok else _DEMOTE[base], quote=av.quote, quote_verified=ok,
            source="ai", explanation=av.explanation, evidence_ids=axis.evidence_ids,
            guidance=axis.principle, check_question=axis.check_question,
        ))

    # 3) 코드 계산 신호
    def code_rule(rule_id: str) -> Rule | None:
        r = rb.rules.get(rule_id)
        return r if r is not None and "code" in r.detection.split("+") else None

    job = extraction.job
    if (r := code_rule("H7")) and job.overseas and job.overseas_perks:
        q = job.overseas_quote
        ok = verified(q)
        add(_rule_hit(r, "red" if ok else "yellow", q, ok, "code",
                      f"해외 근무 + {', '.join(job.overseas_perks)}", "red"), r.status)

    # H8 은 폐업만 결정적 신호. 휴업·미등록 번호·형식 오류는 '확인 필요' + 번호 재확인 질문 (오타·휴업 정상 업체 오판 방지)
    if (r := code_rule("H8")) and facts.nts.status == "closed":
        add(_rule_hit(r, _BASE_LEVEL[r.tier], None, None, "code", "국세청 조회 결과: 폐업"), r.status)
    fact_q: list[tuple[str, str]] = []
    if facts.nts.status == "suspended":
        fact_q.append(("NTS", rb.fact_questions.get("nts_suspended", "")))
    if facts.nts.status == "not_registered":
        fact_q.append(("NTS", rb.fact_questions.get("nts_not_registered", "")))
    if any(not getattr(bn, "checksum_ok", True) for bn in business_numbers or []):
        fact_q.append(("BIZNO", rb.fact_questions.get("checksum_invalid", "")))
    number_recheck_needed = bool(fact_q)

    company = extraction.company
    has_company_name = bool(company.name) and (verified(company.name) or verified(company.name_quote))
    # M2: AI 가 '업체명이 전혀 없다'고 직접 판단했거나, AI 가 낸 업체명이 원문에 없을 때(지어낸 이름)만.
    # AI 가 이름을 비워 두기만 한 경우는 업체명 없음으로 단정하지 않는다(v2.1.1, 오탐 개선)
    name_absent = company.name_missing or (bool(company.name) and not has_company_name)
    if (r := code_rule("M2")) and source_channel in config.OFFICIAL_SOURCE_CHANNELS and name_absent:
        add(_rule_hit(r, _BASE_LEVEL[r.tier], None, None, "code", "정식 플랫폼 출처인데 업체명이 없습니다"), r.status)

    if (r := code_rule("M4")) and facts.industry_mismatch is True:
        add(_rule_hit(r, _BASE_LEVEL[r.tier], None, None, "code",
                      facts.industry_mismatch_detail or "등록 업종과 공고 직무가 다릅니다"), r.status)

    wage, assumed_hours = hourly_wage(extraction.pay)
    pay_ok = wage is not None and (verified(extraction.pay.quote) or verified(extraction.pay.amount_text))
    labor_flags: list[Hit] = []
    ratio = float(th.get("excessive_pay_ratio", 3.0))
    if pay_ok:
        if (r := code_rule("S4")) and wage >= config.MINIMUM_WAGE_HOURLY * ratio:
            note = f"시급 환산 약 {wage:,.0f}원 (2026 최저임금의 {wage / config.MINIMUM_WAGE_HOURLY:.1f}배)"
            add(_rule_hit(r, _BASE_LEVEL[r.tier], extraction.pay.quote, True, "code", note), r.status)
        if (r := code_rule("L1")) and not assumed_hours and wage < config.MINIMUM_WAGE_HOURLY:
            labor_flags.append(_rule_hit(r, "none", extraction.pay.quote, True, "code",
                                         f"시급 환산 약 {wage:,.0f}원 < 2026 최저임금 {config.MINIMUM_WAGE_HOURLY:,}원"))

    # 4) 판정기 조종 문장 (AI 탐지 + 코드 패턴)
    anomalies: list[Hit] = []
    x1 = rb.rules.get("X1")
    if x1 is not None and x1.status == "active":
        code_q = detect_injection(masked_text)
        if code_q:
            anomalies.append(_rule_hit(x1, "yellow", code_q, True, "code", "판정 지시 문장 패턴"))
        elif extraction.injection.detected:
            ok = verified(extraction.injection.quote)
            anomalies.append(_rule_hit(x1, "yellow" if ok else "weak", extraction.injection.quote, ok, "ai",
                                       None, "yellow"))
    if not anomalies and "X1" in risk:  # AI 가 signals 쪽에 X1 을 넣은 경우
        anomalies.append(risk["X1"])
    for a in anomalies:
        risk[a.rule_id] = a  # 한 번만 반영

    # 5) 신뢰 신호 (코드만)
    trust: list[Hit] = []
    if (r := code_rule("T2")) and r.status == "active" and source_channel in config.OFFICIAL_SOURCE_CHANNELS:
        trust.append(_rule_hit(r, "none", None, None, "code", config.SOURCE_CHANNELS.get(source_channel)))
    if (r := code_rule("T1")) and r.status == "active" and facts.worknet.match == "match":
        trust.append(_rule_hit(r, "none", None, None, "code", facts.worknet.detail))
    has_trust = bool(trust)

    # 6) 사칭
    impersonation: Hit | None = None
    r = code_rule("I1")
    if r is not None and r.status == "active":
        brand_claim = company.claims_known_brand and (verified(company.brand_quote) or verified(company.brand_name))
        linked = any(t.rule_id == "T1" for t in trust)
        real_mismatch = facts.nps.match == "single" and facts.worknet.match == "mismatch"
        unofficial = bool(set(extraction.contact.channels) & UNOFFICIAL_CONTACTS) or source_channel in {"sns_messenger", "sms"}
        if ((brand_claim and not linked) or real_mismatch) and unofficial:
            why = (f"'{company.brand_name or company.name}' 이름을 내세우지만 공식 공고와 연결이 확인되지 않고 "
                   "문자·개인 메신저·비공식 링크로 연락합니다")
            impersonation = _rule_hit(r, "none", company.brand_quote, brand_claim or None, "code", why)
            impersonation.base_level = impersonation.level = "orange"

    # 7) 등급
    # 같은 강도면 알려진 규칙을 원칙 축보다 먼저 보여 준다
    hits = sorted(risk.values(), key=lambda h: (-LEVEL_RANK[h.level], h.kind != "rule", h.rule_id))
    red = [h for h in hits if h.level == "red"]
    yellow = [h for h in hits if h.level == "yellow"]
    yellow_untrusted = [h for h in hits if h.level == "yellow_untrusted"]
    weak = [h for h in hits if h.level == "weak"]
    green_blockers = [h for h in hits if h.level != "none" and (rb.rules.get(h.rule_id) is not None)
                      and rb.rules[h.rule_id].blocks_green]
    weak_needed = int(th.get("weak_signals_for_yellow", 2))
    if has_trust:
        weak_needed = int(th.get("weak_signals_for_yellow_with_trust", weak_needed))
    max_weak_green = int(th.get("max_weak_signals_for_green", 1))
    reasons: list[str] = []
    novel = False

    if red:
        grade = "red"
        novel = not any(h.kind == "rule" for h in red)
        reasons.append("결정적 위험 신호: " + ", ".join(h.name for h in red))
        if novel:
            reasons.append("알려진 수법 목록에는 없지만, 일자리의 기본 원칙을 어기는 내용이 있습니다(신종 의심).")
    elif impersonation:
        grade = "orange"
        reasons.append(impersonation.explanation or impersonation.name)
    elif yellow or len(weak) >= weak_needed or (yellow_untrusted and not has_trust):
        grade = "yellow"
        rule_yellow = [h for h in yellow if h.kind == "rule"]
        novel = not rule_yellow and len(weak) < weak_needed
        if yellow:
            reasons.append("주의 신호: " + ", ".join(h.name for h in yellow))
        if yellow_untrusted and not has_trust:
            reasons.append("원칙 위반 의심: " + ", ".join(h.name for h in yellow_untrusted))
        if len(weak) >= weak_needed:
            reasons.append(f"약한 신호 {len(weak)}개: " + ", ".join(h.name for h in weak))
        if novel:
            reasons.append("알려진 수법 목록에는 없지만 원칙에 어긋나는 부분이 있습니다(신종 의심).")
    elif has_trust and len(weak) <= max_weak_green and not number_recheck_needed and not green_blockers:
        grade = "green"
        reasons.append("신뢰 신호: " + ", ".join(t.name for t in trust))
        reasons.append("결정적·중간 위험 신호를 찾지 못했습니다. 위험이 전혀 없다는 뜻은 아니니 근로계약서를 꼭 확인하세요.")
    else:
        grade = "white"
        if number_recheck_needed:
            reasons.append("결정적·중간 위험 신호는 찾지 못했지만, 사업자등록번호를 다시 확인해야 합니다.")
        elif green_blockers:
            reasons.append("결정적·중간 위험 신호는 찾지 못했지만, " + ", ".join(h.name for h in green_blockers)
                           + " — 확인 전에는 낮은 위험으로 단정하지 않습니다.")
        else:
            reasons.append("결정적·중간 위험 신호는 찾지 못했지만, 업체와 공고의 연결을 확인할 신뢰 신호가 없습니다.")

    if any(h.demoted and h.source == "ai" for h in hits) or any(a.demoted for a in anomalies):
        reasons.append("AI가 제시한 근거 문장 중 원문에서 확인되지 않은 것은 한 단계 낮춰 반영했습니다.")

    # 8) 확인 필요 정보
    info = _info_needed(extraction, facts, source_channel, has_trust, has_company_name, business_numbers)

    # 9) 법적 안내·신고처·확인 질문
    shown = [h for h in hits if h.level in {"red", "yellow"}]
    legal_notes = [
        {"rule_id": h.rule_id, "name": h.name, "text": h.legal_note, "evidence_ids": list(h.evidence_ids)}
        for h in shown if h.legal_note
    ]
    contacts = _report_contacts(rb, shown, grade, masked_text)
    questions = _check_questions(rb, grade, hits, impersonation, labor_flags, extraction.follow_up_questions, fact_q)

    g = rb.grades[grade]
    return Verdict(
        grade=grade,
        emoji=g["emoji"],
        label=g["label"],
        novel_suspect=novel,
        reasons=reasons,
        hits=hits,
        trust=trust,
        impersonation=impersonation,
        anomalies=anomalies,
        labor_flags=labor_flags,
        candidate_hits=sorted(candidates.values(), key=lambda h: h.rule_id),
        info_needed=info,
        legal_notes=legal_notes,
        report_contacts=contacts,
        check_questions=questions,
        ignored_signal_ids=ignored,
        hourly_wage=round(wage, 1) if wage is not None and pay_ok else None,
        rules_version=rb.version,
    )


def _info_needed(extraction: Extraction, facts: Facts, source_channel: str, has_trust: bool,
                 has_company_name: bool, business_numbers: list | None) -> list[str]:
    info: list[str] = []
    if not has_company_name and source_channel not in config.OFFICIAL_SOURCE_CHANNELS:
        info.append("공고에 업체명이 없어 업체를 확인할 수 없습니다.")
    for bn in business_numbers or []:
        if not getattr(bn, "checksum_ok", True):
            info.append(f"사업자등록번호 {bn.formatted} 의 형식(검증 숫자)이 맞지 않습니다. 잘못 적혔을 수 있습니다.")
    nts, nps, wn = facts.nts, facts.nps, facts.worknet
    if nts.status == "not_registered":
        info.append("국세청에 등록되지 않은 사업자등록번호로 조회됩니다(오타일 수 있음). 구인자에게 번호를 다시 확인해 주세요.")
    elif nts.status == "suspended":
        info.append("국세청 조회 결과 휴업 상태입니다. 지금 영업 중인지 구인자에게 확인이 필요합니다.")
    if nps.match == "multiple":
        info.append("같은 이름의 사업장이 여러 곳이라 하나로 특정하지 못했습니다. 후보 중에서 골라 주세요.")
    elif nps.match == "none":
        info.append("국민연금 가입 사업장에서 찾지 못했습니다. 1인·미가입 사업장일 수 있어 위험 신호로 보지는 않습니다.")
    for label, res in (("국세청 사업자 상태", nts.status), ("국민연금 사업장", nps.match), ("워크넷 채용정보", wn.match)):
        if res == "error":
            info.append(f"{label} 조회에 실패했습니다. 나머지 정보로 판정했습니다.")
    if source_channel not in config.OFFICIAL_SOURCE_CHANNELS and not has_trust:
        info.append("공식 채용 플랫폼이 아닌 경로로 받은 공고라, 업체와 공고의 연결을 직접 확인해야 합니다.")
    missing = [m.strip() for m in extraction.missing_info if m and m.strip()]
    if missing:
        info.append("공고에 빠진 정보: " + ", ".join(dict.fromkeys(missing)))
    return info


def _report_contacts(rb: RuleBook, shown: list[Hit], grade: str, masked_text: str) -> list[dict]:
    keys: set[str] = set()
    for h in shown:
        rule = rb.rules.get(h.rule_id)
        if rule is None:
            continue
        keys.update(rule.report_to)
        for contact, words in rule.extra_report_if_keywords.items():
            if any(w in masked_text for w in words):
                keys.add(contact)
    if grade == "red":
        keys.add("police")
    ordered = [k for k in _CONTACT_ORDER if k in keys] + sorted(k for k in keys if k not in _CONTACT_ORDER)
    return [{"key": k, **rb.contacts[k]} for k in ordered if k in rb.contacts]


def _check_questions(rb: RuleBook, grade: str, hits: list[Hit], impersonation: Hit | None,
                     labor_flags: list[Hit], ai_questions: list[str] | None = None,
                     fact_questions: list[tuple[str, str]] | None = None) -> list[dict]:
    """순서: 사업자번호 재확인 → 사칭 → 걸린 신호별(규칙 문구) → AI 맞춤 질문 → 근로조건 → 일반 질문."""
    out: list[dict] = []
    seen: set[str] = set()

    def push(rule_id: str, q: str | None) -> None:
        if q and q not in seen:
            seen.add(q)
            out.append({"rule_id": rule_id, "question": q})

    for rid, q in fact_questions or []:
        push(rid, q)
    if impersonation:
        push(impersonation.rule_id, impersonation.check_question)
    for h in hits:
        if h.level != "none":
            push(h.rule_id, h.check_question)
    for q in (ai_questions or [])[:3]:
        push("AI", q.strip() if q else None)
    for f in labor_flags:
        push(f.rule_id, f.check_question)
    if grade in {"white", "yellow", "orange"}:
        for q in rb.general_questions:
            push("GENERAL", q)
    return out
