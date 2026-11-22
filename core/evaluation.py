"""검증: 테스트셋·외부 확인셋 판정, 지표, 기준선 2종, '유형 하나 빼기'(신종 탐지율).

노트북(notebooks/eval.ipynb)이 이 모듈을 부른다. AI 호출 결과(추출값·토큰)는 캐시 파일에 저장해 다시 돌릴 때 비용이 들지 않게 한다.

지표 정의(data/testset/README.md)
- 탐지율(사기): 예측 등급이 🔴·🟠·🟡 중 하나인 비율 / 엄격 일치: acceptable_grades 안
- 오탐률(정상): 예측 등급이 🔴·🟠·🟡 중 하나인 비율 (정상 클래스별)
- 신종 탐지율('유형 하나 빼기'): 그룹 X 의 정답 규칙을 지운 규칙으로 X 시나리오를 다시 판정했을 때 🔴·🟠·🟡 비율.
  추출 결과를 재사용하므로 추가 비용이 없다. 한계: 실제로는 그 규칙이 프롬프트에도 없어 AI 추출이 달라질 수 있다.
- 인용 검증 통과율: AI 가 낸 근거 문장 가운데 마스킹된 원문에서 확인된 비율
기준선
- 키워드: AI 없이 rules.yaml 의 예시 표현(정규화한 구절)이 원문에 그대로 있는지만 보고 같은 규칙 엔진으로 판정
- 범용 프롬프트: 같은 모델에 공고만 주고 위험 여부(높음·중간·낮음·판단 불가)를 한 번 묻는 방식
"""
from __future__ import annotations

import copy
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, Field

from . import config
from .extract import estimate_cost_usd
from .masking import Masker, normalize_for_match
from .rules_engine import RuleBook, judge, load_rules, rulebook_from_dict
from .samples import FLAGGED_GRADES, extraction_from_partial
from .schema import Extraction, Facts

EXTERNAL_SET_PATH = config.TESTSET_DIR / "external_set.yaml"
TRUST_RULES = {"T1", "T2"}


# ---------------------------------------------------------------------------
# 데이터
# ---------------------------------------------------------------------------
def load_items(path: Path | None = None) -> list[dict]:
    p = path or (config.TESTSET_DIR / "testset.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))["items"]


def load_groups(path: Path | None = None) -> dict:
    p = path or (config.TESTSET_DIR / "testset.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))["meta"]["groups"]


# ---------------------------------------------------------------------------
# AI 추출 (캐시)
# ---------------------------------------------------------------------------
def extract_all(items: list[dict], extractor_factory: Callable[[], object], cache_path: Path,
                log: Callable[[str], None] = print) -> dict:
    """항목마다 마스킹 → AI 추출. 캐시에 있으면 건너뛴다(재실행 무비용). 반환: id → 기록."""
    cache: dict = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    for it in items:
        if it["id"] in cache and "extraction" in cache[it["id"]]:
            continue
        masked = Masker().mask(it["text"]).masked_text
        ex = extractor_factory()
        t0 = time.time()
        try:
            extraction = ex(masked, it["source_channel"], 1)
            rec = {"masked_text": masked, "extraction": extraction.model_dump(), "usage": getattr(ex, "last_usage", None),
                   "seconds": round(time.time() - t0, 1)}
        except Exception as exc:  # 한 건 실패해도 계속
            rec = {"masked_text": masked, "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - t0, 1)}
        cache[it["id"]] = rec
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"{it['id']}: {'오류' if 'error' in rec else 'ok'} ({rec['seconds']}s)")
    return cache


# ---------------------------------------------------------------------------
# 판정·지표
# ---------------------------------------------------------------------------
@dataclass
class ItemResult:
    id: str
    group: str
    cls: str
    source_channel: str
    expected_grade: str
    acceptable: list[str]
    predicted: str | None
    matched_ids: list[str] = field(default_factory=list)
    novel: bool = False
    quotes_total: int = 0
    quotes_ok: int = 0
    cost: float | None = None
    usage: dict | None = None
    seconds: float | None = None
    error: str | None = None

    @property
    def flagged(self) -> bool:
        return self.predicted in FLAGGED_GRADES

    @property
    def strict_ok(self) -> bool:
        return self.predicted in self.acceptable


def _result(it: dict, **kw) -> ItemResult:
    return ItemResult(id=it["id"], group=it["group"], cls=it["class"], source_channel=it["source_channel"],
                      expected_grade=it["expected_grade"], acceptable=list(it["acceptable_grades"]), **kw)


def judge_items(items: list[dict], cache: dict, rulebook: RuleBook | None = None) -> list[ItemResult]:
    rb = rulebook or load_rules()
    out = []
    for it in items:
        rec = cache.get(it["id"])
        if rec is None or "extraction" not in rec:
            out.append(_result(it, predicted=None, error=(rec or {}).get("error", "추출 없음")))
            continue
        ex = Extraction.model_validate(rec["extraction"])
        v = judge(ex, rec["masked_text"], it["source_channel"], facts=Facts(), rulebook=rb)
        ai_hits = [h for h in v.hits + v.anomalies if h.source == "ai" and h.quote_verified is not None]
        out.append(_result(
            it, predicted=v.grade, matched_ids=v.matched_ids, novel=v.novel_suspect,
            quotes_total=len(ai_hits), quotes_ok=sum(1 for h in ai_hits if h.quote_verified),
            cost=estimate_cost_usd(rec.get("usage")), usage=rec.get("usage"), seconds=rec.get("seconds"),
        ))
    return out


def summarize(results: list[ItemResult], groups: dict | None = None) -> dict:
    """그룹별·전체 지표 표(노트북에서 표로 보여 줌)."""
    groups = groups or {}
    rows = []
    for g in sorted({r.group for r in results}, key=lambda x: (x[0] != "G", int(re.sub(r"\D", "", x) or 0))):
        rs = [r for r in results if r.group == g]
        cls = rs[0].cls
        n = len(rs)
        flagged = sum(r.flagged for r in rs)
        rows.append({
            "그룹": g, "이름": (groups.get(g) or {}).get("name", ""), "구분": "사기" if cls == "scam" else "정상", "N": n,
            "탐지율(🔴🟠🟡)" if cls == "scam" else "오탐률(🔴🟠🟡)": round(flagged / n, 3),
            "엄격 일치": round(sum(r.strict_ok for r in rs) / n, 3),
            "예측 등급": ", ".join(str(r.predicted) for r in rs),
        })
    scam = [r for r in results if r.cls == "scam" and r.predicted]
    normal = [r for r in results if r.cls == "normal" and r.predicted]
    qt = sum(r.quotes_total for r in results)
    costs = [r.cost for r in results if r.cost is not None]
    secs = [r.seconds for r in results if r.seconds is not None]
    overall = {
        "사기 N": len(scam), "탐지율": round(sum(r.flagged for r in scam) / len(scam), 3) if scam else None,
        "사기 엄격 일치": round(sum(r.strict_ok for r in scam) / len(scam), 3) if scam else None,
        "정상 N": len(normal), "오탐률": round(sum(r.flagged for r in normal) / len(normal), 3) if normal else None,
        "정상 엄격 일치": round(sum(r.strict_ok for r in normal) / len(normal), 3) if normal else None,
        "인용 검증 통과율": round(sum(r.quotes_ok for r in results) / qt, 3) if qt else None,
        "인용 수": qt,
        "건당 평균 비용($)": round(sum(costs) / len(costs), 4) if costs else None,
        "건당 평균 시간(초)": round(sum(secs) / len(secs), 1) if secs else None,
        "오류 수": sum(1 for r in results if r.error),
    }
    return {"groups": rows, "overall": overall}


# ---------------------------------------------------------------------------
# 기준선 1: 키워드 (AI 없음)
# ---------------------------------------------------------------------------
_PLACEHOLDER = re.compile(r"O{2,}|○+")


def keyword_fragments(rb: RuleBook) -> dict[str, list[str]]:
    """rules.yaml 예시 표현 → 규칙별 정규화 구절(3자 이상). 'OO'·'○○' 같은 자리표시는 구절을 끊는다."""
    out: dict[str, list[str]] = {}
    for r in rb.ai_rules():
        frags = []
        for ex in r.examples:
            for part in re.split(r"[/,·()\[\]~+]|\s또는\s", _PLACEHOLDER.sub("/", ex)):
                f = normalize_for_match(part)
                if len(f) >= 3:
                    frags.append(f)
        out[r.id] = sorted(set(frags))
    return out


KEYWORD_EXCLUDED_RULES = {"M2"}  # 업체명 추출이 필요한 규칙 — 키워드 방식은 업체명을 뽑지 못하므로 빼야 공정하다


def keyword_baseline(items: list[dict], rulebook: RuleBook | None = None) -> list[ItemResult]:
    if rulebook is None:
        data = yaml.safe_load(config.RULES_PATH.read_text(encoding="utf-8"))
        data["rules"] = [r for r in data["rules"] if r["id"] not in KEYWORD_EXCLUDED_RULES]
        rulebook = rulebook_from_dict(data)
    rb = rulebook
    frags = keyword_fragments(rb)
    out = []
    for it in items:
        masked = Masker().mask(it["text"]).masked_text
        norm = normalize_for_match(masked)
        signals = []
        for rid, fs in frags.items():
            hit = next((f for f in fs if f in norm), None)
            if hit:
                signals.append({"signal_id": rid, "quote": hit, "explanation": "키워드 일치"})
        ex = extraction_from_partial({"signals": signals})
        v = judge(ex, masked, it["source_channel"], facts=Facts(), rulebook=rb)
        out.append(_result(it, predicted=v.grade, matched_ids=v.matched_ids))
    return out


# ---------------------------------------------------------------------------
# '유형 하나 빼기' (신종 탐지율)
# ---------------------------------------------------------------------------
def group_rules(items: list[dict]) -> dict[str, set[str]]:
    """사기 그룹별 '그 유형 전용 규칙' = 그 그룹 정답 규칙의 합집합(신뢰 규칙 제외)."""
    out: dict[str, set[str]] = {}
    for it in items:
        if it["class"] == "scam":
            out.setdefault(it["group"], set()).update(set(it["expected_rules"]) - TRUST_RULES)
    return out


def leave_one_out(items: list[dict], cache: dict, rules_data: dict | None = None) -> tuple[list[ItemResult], dict]:
    data = rules_data or yaml.safe_load(config.RULES_PATH.read_text(encoding="utf-8"))
    out: list[ItemResult] = []
    removed_map = {}
    for g, removed in group_rules(items).items():
        d = copy.deepcopy(data)
        d["rules"] = [r for r in d["rules"] if r["id"] not in removed]
        rb = rulebook_from_dict(d)
        removed_map[g] = sorted(removed)
        out.extend(judge_items([it for it in items if it["group"] == g], cache, rb))
    return out, removed_map


# ---------------------------------------------------------------------------
# 기준선 2: 범용 프롬프트 한 번 (같은 모델)
# ---------------------------------------------------------------------------
class GeneralVerdict(BaseModel):
    risk: Literal["high", "medium", "low", "unknown"] = Field(description="사기·범죄가담 위험")
    reason: str


GENERAL_PROMPT = ("다음은 구직자가 받은 구인 공고나 메시지입니다. 취업사기나 범죄 가담 위험이 있는지 판단해 "
                  "high / medium / low / unknown 중 하나와 이유 한 문장을 답하세요.")
GENERAL_TO_GRADE = {"high": "red", "medium": "yellow", "low": "green", "unknown": "white"}


def general_prompt_baseline(items: list[dict], client, model: str, cache_path: Path,
                            log: Callable[[str], None] = print) -> list[ItemResult]:
    cache: dict = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    out = []
    for it in items:
        if it["id"] not in cache:
            masked = Masker().mask(it["text"]).masked_text  # 기준선도 같은 마스킹 후 전송
            t0 = time.time()
            try:
                resp = client.responses.parse(model=model, instructions=GENERAL_PROMPT,
                                              input=[{"role": "user", "content": masked}],
                                              text_format=GeneralVerdict, reasoning={"effort": "low"},
                                              max_output_tokens=4000, store=False)
                parsed = resp.output_parsed
                u = resp.usage
                usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                         "cached_input_tokens": getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0)}
                cache[it["id"]] = {"risk": parsed.risk if parsed else "unknown", "reason": parsed.reason if parsed else "",
                                   "usage": usage, "seconds": round(time.time() - t0, 1)}
            except Exception as exc:
                cache[it["id"]] = {"error": f"{type(exc).__name__}: {exc}"}
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"{it['id']}: {cache[it['id']].get('risk', '오류')}")
        rec = cache[it["id"]]
        if "error" in rec:
            out.append(_result(it, predicted=None, error=rec["error"]))
        else:
            out.append(_result(it, predicted=GENERAL_TO_GRADE[rec["risk"]], cost=estimate_cost_usd(rec.get("usage")),
                               usage=rec.get("usage"), seconds=rec.get("seconds")))
    return out


def novel_suspects_from_loo(items: list[dict], cache: dict, rules_data: dict | None = None) -> list[tuple]:
    """'유형 하나 빼기'에서 '신종 의심'으로 판정된 항목 → (item, 캐시 기록, Verdict). 학습 고리 시험 사례로 쓴다."""
    data = rules_data or yaml.safe_load(config.RULES_PATH.read_text(encoding="utf-8"))
    out = []
    for g, removed in group_rules(items).items():
        d = copy.deepcopy(data)
        d["rules"] = [r for r in d["rules"] if r["id"] not in removed]
        rb = rulebook_from_dict(d)
        for it in [x for x in items if x["group"] == g]:
            rec = cache.get(it["id"])
            if not rec or "extraction" not in rec:
                continue
            v = judge(Extraction.model_validate(rec["extraction"]), rec["masked_text"], it["source_channel"],
                      facts=Facts(), rulebook=rb)
            if v.novel_suspect:
                out.append((it, rec, v))
    return out


def results_to_records(results: list[ItemResult]) -> list[dict]:
    return [dict(asdict(r), flagged=r.flagged, strict_ok=r.strict_ok) for r in results]
