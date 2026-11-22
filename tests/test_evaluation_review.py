"""검증·규칙 검토 모듈 테스트 (API 호출 없음)."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import yaml

from conftest import axis, make_extraction, sig
from core import config, evaluation as ev, review
from core.masking import Masker
from core.rules_engine import load_rules
from core.samples import load_testset, validate_testset

RB = load_rules()
KST = timezone(timedelta(hours=9))

ITEMS = [
    {"id": "A-1", "group": "G5", "class": "scam", "source_channel": "sns_messenger",
     "text": "고액 운반 알바. 물건 받아서 다른 장소에 두고 오기만 하면 건당 50만 원.", "expected_grade": "red",
     "acceptable_grades": ["red"], "expected_rules": ["H2"]},
    {"id": "N-1", "group": "N1", "class": "normal", "source_channel": "platform",
     "text": "가상제빵 주말 매장 스태프, 시급 11,000원, 근로계약서 작성", "expected_grade": "green",
     "acceptable_grades": ["green"], "expected_rules": ["T2"]},
]


def _cache():
    m1 = Masker().mask(ITEMS[0]["text"]).masked_text
    m2 = Masker().mask(ITEMS[1]["text"]).masked_text
    e1 = make_extraction(signals=[sig("H2", "물건 받아서 다른 장소에 두고 오기만 하면")],
                         axes=[axis("B", "물건 받아서 다른 장소에 두고 오기만 하면")])
    e2 = make_extraction(company_name="가상제빵")
    usage = {"input_tokens": 5700, "cached_input_tokens": 3000, "output_tokens": 900}
    return {"A-1": {"masked_text": m1, "extraction": e1.model_dump(), "usage": usage, "seconds": 10.0},
            "N-1": {"masked_text": m2, "extraction": e2.model_dump(), "usage": usage, "seconds": 9.0}}


def test_judge_and_summarize():
    res = ev.judge_items(ITEMS, _cache(), RB)
    assert [r.predicted for r in res] == ["red", "green"]
    o = ev.summarize(res)["overall"]
    assert o["탐지율"] == 1.0 and o["오탐률"] == 0.0 and o["인용 검증 통과율"] == 1.0
    assert o["건당 평균 비용($)"] == round((2700 * 2 + 3000 * 0.1 + 900 * 10) / 1e6, 4)


def test_missing_extraction_is_reported_not_crashing():
    res = ev.judge_items(ITEMS, {"A-1": {"masked_text": "x", "error": "Timeout"}}, RB)
    assert res[0].predicted is None and res[0].error == "Timeout"
    assert ev.summarize(res)["overall"]["오류 수"] == 2


def test_leave_one_out_uses_principle_layer():
    loo, removed = ev.leave_one_out(ITEMS, _cache())
    assert removed == {"G5": ["H2"]}
    assert loo[0].predicted == "red" and loo[0].novel  # H2 를 빼도 원칙 B 로 🔴(신종 의심)
    novel = ev.novel_suspects_from_loo(ITEMS, _cache())
    assert [it["id"] for it, _, _ in novel] == ["A-1"]


def test_keyword_baseline_matches_example_phrases_only():
    frags = ev.keyword_fragments(RB)
    assert all(len(f) >= 3 for fs in frags.values() for f in fs)
    assert not any("oo" in f for fs in frags.values() for f in fs)
    exact = [dict(ITEMS[0], text="지인 소개 수당 따로 드립니다")]
    kw = ev.keyword_baseline(exact)[0]
    assert kw.predicted == "red" and "H6" in kw.matched_ids  # H6 예시 표현 '지인 소개 수당' 과 같다
    assert len(ev.load_items(ev.EXTERNAL_SET_PATH)) == 3  # E63 문구는 이용 조건 때문에 제외
    paraphrased = [dict(ITEMS[0], text="내용물은 묻지 말고 박스만 다른 주소로 옮겨 주세요. 건당 50만 원")]
    assert ev.keyword_baseline(paraphrased)[0].predicted != "red"  # 표현이 바뀌면 키워드는 놓친다


def test_general_prompt_baseline_with_fake_client(tmp_path):
    class Resp:
        output_parsed = ev.GeneralVerdict(risk="high", reason="현금 운반")
        usage = SimpleNamespace(input_tokens=300, output_tokens=50, input_tokens_details=SimpleNamespace(cached_tokens=0))

    calls = []
    client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kw: calls.append(kw) or Resp()))
    res = ev.general_prompt_baseline(ITEMS[:1], client, "gpt-6.2-sol", tmp_path / "g.json", log=lambda *_: None)
    assert res[0].predicted == "red" and calls[0]["store"] is False
    assert "물건 받아서" in calls[0]["input"][0]["content"]
    ev.general_prompt_baseline(ITEMS[:1], client, "gpt-6.2-sol", tmp_path / "g.json", log=lambda *_: None)
    assert len(calls) == 1  # 캐시 재사용


def test_external_set_is_valid_and_literal():
    data = yaml.safe_load(ev.EXTERNAL_SET_PATH.read_text(encoding="utf-8"))
    assert validate_testset(data, set(RB.rules)) == []
    for it in data["items"]:
        assert it["url"].startswith("https://www.korea.kr/") and it["license"]


# ---------------------------------------------------------------------------
# 규칙 검토
# ---------------------------------------------------------------------------
def _cases():
    c = _cache()["A-1"]
    v = ev.judge_items(ITEMS[:1], _cache(), RB)
    from core.rules_engine import judge
    from core.schema import Extraction, Facts
    verdict = judge(Extraction.model_validate(c["extraction"]), c["masked_text"], "sns_messenger", facts=Facts())
    case = review.case_from_eval(ITEMS[0], c, verdict)
    case["_path"] = f"cases/2026-11-23/{case['case_id']}.json"
    return [case]


def _draft(case_id):
    return review.ReviewDraft(
        clusters=[review.CaseCluster(label="물건 운반", case_ids=[case_id], summary="내용물 미상 물건 운반")],
        candidates=[review.CandidateRule(
            suggested_id="C01", tier="H", axis="B", name="후보: 물건 두고 오기", description="받은 물건을 지정 장소에 두고 오게 함",
            examples=["다른 장소에 두고 오기만 하면", "지어낸 표현"], check_question="물건의 내용물은 무엇인가요?",
            case_ids=[case_id], rationale="테스트", evidence_search_hint="마약 운반 알바")])


def test_case_from_eval_is_marked_synthetic():
    case = _cases()[0]
    assert case["synthetic"] and case["trigger"] == "synthetic_eval" and case["testset_id"] == "A-1"
    assert case["verdict"]["novel_suspect"] is False  # H2 가 있는 원래 규칙 기준


def test_approval_requires_evidence_and_human_and_keeps_only_real_examples():
    cases = _cases()
    draft = _draft(cases[0]["case_id"])
    data = yaml.safe_load(config.RULES_PATH.read_text(encoding="utf-8"))
    _, added = review.apply_approvals(data, draft, {"approvals": [{"suggested_id": "C01", "rule_id": "H9", "approver": "운영자"}]}, cases)
    assert added == []  # 근거 ID 없으면 승인 안 됨
    new, added = review.apply_approvals(data, draft, {"approvals": [
        {"suggested_id": "C01", "rule_id": "H9", "evidence_ids": ["E61"], "approver": "운영자", "status": "candidate"}]}, cases)
    assert [r["id"] for r in added] == ["H9"] and added[0]["examples"] == ["다른 장소에 두고 오기만 하면"]
    diff = review.rules_yaml_diff(config.RULES_PATH.read_text(encoding="utf-8"), added)
    assert "+  - id: H9" in diff and "변경안" in diff
    reg = review.regression(new, ITEMS, _cache())
    assert reg["ok"] and reg["changes"] == []


def test_purge_expired_and_load_from_dir(tmp_path):
    case = _cases()[0]
    d = tmp_path / "cases" / "2026-11-23"
    d.mkdir(parents=True)
    old = dict(case, case_id="old", expires_at="2026-01-01")
    (d / "old.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    (d / "new.json").write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    cases = review.load_cases_from_dir(tmp_path / "cases")
    deleted = []
    api = SimpleNamespace(delete_file=lambda path, repo, **kw: deleted.append(path))
    targets = review.purge_expired(cases, api=api, token="t", repo_id="r")
    assert targets == ["cases/2026-11-23/old.json"] == deleted
    assert review.purge_expired(cases, dry_run=True) == targets
