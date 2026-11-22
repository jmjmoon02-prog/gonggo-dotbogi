"""notebooks/eval.ipynb, notebooks/rule_review.ipynb 생성(코드는 core/ 모듈을 부르는 얇은 셀).

실행: (app 폴더에서) .venv/Scripts/python.exe scripts/build_notebooks.py
노트북 실행: .venv/Scripts/python.exe scripts/run_notebook.py notebooks/eval.ipynb
"""
from pathlib import Path

import nbformat as nbf

NB_DIR = Path(__file__).resolve().parent.parent / "notebooks"

SETUP = r'''# 환경 준비: Colab 이면 배포용 공개 저장소(app/ 만 담은 저장소)를 받아 오고, 키는 Colab '보안 비밀'에서 읽는다.
import os, sys, json, pathlib, warnings
warnings.filterwarnings("ignore")  # 라이브러리 경고(로컬 경로가 찍힘)를 실행 기록에 남기지 않는다
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
IN_COLAB = "google.colab" in sys.modules
if IN_COLAB:
    APP_REPO_URL = "https://github.com/jmjmoon02-prog/gonggo-dotbogi.git"  # 배포용 저장소(app/ 만, 제출 시 공개)
    if not pathlib.Path("app").exists():
        !git clone -q $APP_REPO_URL app
    !pip install -q -r app/requirements.txt
    from google.colab import userdata
    for k in ["OPENAI_API_KEY", "MODEL_ID", "HF_TOKEN", "HF_DATASET_REPO"]:
        try:
            os.environ[k] = userdata.get(k)
        except Exception:
            pass
    APP_DIR = pathlib.Path("app").resolve()
else:
    APP_DIR = pathlib.Path.cwd().resolve().parent  # notebooks/ 의 상위 = app/
sys.path.insert(0, str(APP_DIR))
RESULTS = APP_DIR / "notebooks" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
import pandas as pd
pd.set_option("display.max_colwidth", 80)
from core import config
print("app:", APP_DIR.name, "| model:", config.model_id(), "| OpenAI 키:", "있음" if config.get_secret("OPENAI_API_KEY") else "없음")'''


def md(text):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text):
    return nbf.v4.new_code_cell(text.strip())


def eval_notebook():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""
# 공고돋보기 — 검증 노트북 (eval)
테스트셋 53건(가상, AI로 초안 작성)과 외부 확인셋 3건(공식 자료의 공고 문구 원문)으로 판정 품질을 잰다.

| 지표 | 정의 |
|---|---|
| 탐지율(사기) | 예측 등급이 🔴·🟠·🟡 중 하나인 비율 (엄격 일치 = 허용 등급 안) |
| 오탐률(정상) | 정상 공고가 🔴·🟠·🟡로 나온 비율, 정상 클래스별 |
| 신종 탐지율 | '유형 하나 빼기': 그 유형의 정답 규칙을 지우고 다시 판정했을 때 🔴·🟠·🟡 비율 (AI 추출 재사용, 무비용) |
| 인용 검증 통과율 | AI가 낸 근거 문장 중 마스킹된 원문에서 코드로 확인된 비율 |
| 기준선 | ① AI 없이 rules.yaml 예시 표현 키워드 일치만 ② 같은 모델에 공고만 주고 위험 여부를 한 번 묻기 |

- AI에는 **마스킹된 가상 데이터만** 보낸다. 호출 결과는 `results/` 캐시에 저장해 다시 실행할 때 비용이 들지 않는다.
- 한계: 테스트셋은 규칙을 만든 쪽이 작성해 순환 위험이 있다(외부 확인셋으로 일부 보완). '유형 하나 빼기'는 추출을 재사용하므로, 실제로 규칙이 프롬프트에 없을 때보다 낙관적일 수 있다.
"""),
        code(SETUP),
        code(r'''
RUN_AI = True                 # 테스트셋·외부 확인셋 AI 판정 (캐시에 있으면 건너뜀)
RUN_GENERAL_BASELINE = True   # 기준선 ② (같은 모델에 위험 여부만 묻기)
SAVE_SYNTHETIC_CASES = True   # '유형 하나 빼기'의 신종 의심 사례를 '평가용 가상 사례'로 HF 에 저장(학습 고리 시험용)

from core import evaluation as ev
from core.extract import OpenAIExtractor, make_client
from core.rules_engine import load_rules
RB = load_rules()
items = ev.load_items()
ext_items = ev.load_items(ev.EXTERNAL_SET_PATH)
groups = {**ev.load_groups(), **ev.load_groups(ev.EXTERNAL_SET_PATH)}
print(f"테스트셋 {len(items)}건 (사기 {sum(i['class']=='scam' for i in items)} / 정상 {sum(i['class']=='normal' for i in items)}), 외부 확인셋 {len(ext_items)}건, 규칙 v{RB.version}")
'''),
        md("## 1. AI 판정 (마스킹 → 구조화 추출 → 규칙 엔진)"),
        code(r'''
client = make_client() if RUN_AI else None
factory = lambda: OpenAIExtractor(client=client, rulebook=RB)
cache = ev.extract_all(items, factory, RESULTS / "eval_cache_testset.json") if RUN_AI else json.loads((RESULTS / "eval_cache_testset.json").read_text(encoding="utf-8"))
ext_cache = ev.extract_all(ext_items, factory, RESULTS / "eval_cache_external.json") if RUN_AI else json.loads((RESULTS / "eval_cache_external.json").read_text(encoding="utf-8"))
res = ev.judge_items(items, cache, RB)
ext_res = ev.judge_items(ext_items, ext_cache, RB)
s = ev.summarize(res, groups)
display(pd.DataFrame(s["groups"]))
display(pd.DataFrame([s["overall"]]))
'''),
        md("## 2. 외부 확인셋 (공식 자료 공고 문구 원문)"),
        code(r'''
se = ev.summarize(ext_res, groups)
display(pd.DataFrame(se["groups"]))
display(pd.DataFrame([{"id": r.id, "기대": r.expected_grade, "예측": r.predicted, "걸린 규칙": ",".join(r.matched_ids)} for r in ext_res]))
'''),
        md("## 3. 기준선 비교"),
        code(r'''
kw = ev.keyword_baseline(items); kw_ext = ev.keyword_baseline(ext_items)  # 업체명 추출이 필요한 M2 는 제외(공정 비교)
gen = gen_ext = None
if RUN_GENERAL_BASELINE:
    gc = client or make_client()
    gen = ev.general_prompt_baseline(items, gc, config.model_id(), RESULTS / "eval_cache_general_testset.json")
    gen_ext = ev.general_prompt_baseline(ext_items, gc, config.model_id(), RESULTS / "eval_cache_general_external.json")
def row(name, r, r_ext):
    o = ev.summarize(r)["overall"]; oe = ev.summarize(r_ext)["overall"] if r_ext else {}
    return {"방식": name, "탐지율": o["탐지율"], "사기 엄격 일치": o["사기 엄격 일치"], "오탐률": o["오탐률"],
            "외부 확인셋 탐지율": oe.get("탐지율"), "건당 비용($)": o["건당 평균 비용($)"]}
compare = [row("공고돋보기 (AI 추출 + 규칙 엔진)", res, ext_res), row("기준선① 키워드만 (AI 없음)", kw, kw_ext)]
if gen:
    compare.append(row("기준선② 범용 프롬프트 한 번", gen, gen_ext))
display(pd.DataFrame(compare))
display(pd.DataFrame(ev.summarize(kw, groups)["groups"])[["그룹", "구분", "N", "탐지율(🔴🟠🟡)", "오탐률(🔴🟠🟡)", "예측 등급"]])
if gen:
    display(pd.DataFrame(ev.summarize(gen, groups)["groups"])[["그룹", "구분", "N", "탐지율(🔴🟠🟡)", "오탐률(🔴🟠🟡)", "예측 등급"]])
'''),
        md("## 4. 신종 탐지율 ('유형 하나 빼기', 무비용)"),
        code(r'''
loo, removed = ev.leave_one_out(items, cache)
rows = []
for g, rm in removed.items():
    rs = [r for r in loo if r.group == g]
    rows.append({"유형": g, "이름": groups[g]["name"], "뺀 규칙": ",".join(rm), "N": len(rs),
                 "탐지(🔴🟠🟡)": sum(r.flagged for r in rs), "그중 신종 의심 표시": sum(r.novel for r in rs),
                 "예측 등급": ", ".join(str(r.predicted) for r in rs)})
loo_df = pd.DataFrame(rows); display(loo_df)
loo_scam = [r for r in loo]
novel_rate = round(sum(r.flagged for r in loo_scam) / len(loo_scam), 3)
print("신종 탐지율(유형 하나 빼기):", novel_rate, f"({sum(r.flagged for r in loo_scam)}/{len(loo_scam)})")
'''),
        md("## 5. 비용·결과 저장"),
        code(r'''
costs = [r.cost for r in res if r.cost is not None]
cached = [ (r.usage or {}).get("cached_input_tokens") or 0 for r in res if r.usage]
print(f"테스트셋 판정 1건(1회차 텍스트) 평균 ${sum(costs)/len(costs):.4f} (N={len(costs)}), 평균 캐시 입력 {sum(cached)/len(cached):,.0f} 토큰")
summary = {
    "run_at": pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds"), "model": config.model_id(), "rules_version": RB.version,
    "testset": s["overall"], "external": se["overall"], "compare": compare, "novel_detection_rate": novel_rate,
    "leave_one_out": rows, "groups": s["groups"],
}
(RESULTS / "eval_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
(RESULTS / "eval_items.json").write_text(json.dumps(ev.results_to_records(res + ext_res), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print("저장:", (RESULTS / "eval_summary.json").name, (RESULTS / "eval_items.json").name)
'''),
        md("## 6. 학습 고리 시험 사례 저장 (평가용 가상 사례)"),
        code(r'''
from core import storage, review
novel = ev.novel_suspects_from_loo(items, cache)
print("'유형 하나 빼기'에서 신종 의심으로 판정된 항목:", [it["id"] for it, _, _ in novel])
store = storage.get_store()
marker = RESULTS / "synthetic_cases_saved.json"  # 다시 실행해도 같은 사례를 또 올리지 않게
saved = []
if marker.exists():
    print("평가용 가상 사례는 이미 저장됨:", json.loads(marker.read_text(encoding="utf-8")))
elif SAVE_SYNTHETIC_CASES and store is not None and isinstance(store, storage.HFDatasetStore):
    for it, rec, v in novel:
        case = review.case_from_eval(it, rec, v)
        saved.append(store.save(case))
    marker.write_text(json.dumps({"count": len(saved), "testset_ids": [it["id"] for it, _, _ in novel]}, ensure_ascii=False), encoding="utf-8")
    print("저장한 평가용 가상 사례:", len(saved))
'''),
    ]
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    return nb


def review_notebook():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""
# 공고돋보기 — 규칙 검토 노트북 (rule_review, 학습 고리)
저장된 사례(동의 사례·평가용 가상 사례) → 보관 기한 지난 사례 삭제 → **AI가 묶고 규칙 후보 초안** → **사람이 공식 근거를 확인해 승인** → 회귀 시험 → `rules.yaml` 변경안(diff).

- 사용자 피드백·AI 초안만으로는 규칙이 바뀌지 않는다(사람 승인 + 근거 ID 필수).
- 승인된 규칙도 앱에 바로 반영하지 않고 변경안 파일로 낸다. 대회 제출 후에는 규칙을 바꾸지 않는다.
- 사람의 결정은 `notebooks/review_decisions.json` 에 적는다(승인자·근거 ID).
"""),
        code(SETUP),
        md("## 1. 사례 불러오기 · 보관 기한 지난 사례 삭제"),
        code(r'''
import tempfile
from huggingface_hub import HfApi
from core import review, storage
from core import evaluation as ev
from core.rules_engine import load_rules
RB = load_rules()
token, repo = config.get_secret("HF_TOKEN"), config.get_secret("HF_DATASET_REPO")
tmp = pathlib.Path(tempfile.mkdtemp())
cases = review.load_cases_from_hf(token, repo, tmp)
expired = review.purge_expired(cases, api=HfApi(), token=token, repo_id=repo)
cases = [c for c in cases if c["_path"] not in set(expired)]
print(f"사례 {len(cases)}건 (기한 지나 삭제 {len(expired)}건)")
display(pd.DataFrame([{"case_id": c["case_id"], "계기": c.get("trigger_label", c.get("trigger")), "가상": c.get("synthetic", False),
                       "등급": c["verdict"]["grade"], "신종 의심": c["verdict"]["novel_suspect"], "걸린 규칙": ",".join(c["verdict"]["matched_ids"]),
                       "기한": c["expires_at"]} for c in cases]))
'''),
        md("## 2. AI 묶기 · 규칙 후보 초안 (결과는 캐시)"),
        code(r'''
from core.extract import make_client
draft_path = RESULTS / "review_draft.json"
if draft_path.exists():
    draft = review.ReviewDraft.model_validate_json(draft_path.read_text(encoding="utf-8")); usage = None
    print("캐시된 초안 사용(추가 비용 없음)")
else:
    draft, usage = review.draft_candidates(cases, make_client(), config.model_id(), RB)
    draft_path.write_text(draft.model_dump_json(indent=1), encoding="utf-8")
    from core.extract import estimate_cost_usd
    print("초안 생성 비용 약 $", round(estimate_cost_usd(usage) or 0, 4), usage)
display(pd.DataFrame([c.model_dump() for c in draft.clusters]))
cand_rows = []
for c in draft.candidates:
    checks = review.verify_candidate_examples(c, cases)
    cand_rows.append({"임시 ID": c.suggested_id, "등급": c.tier, "축": c.axis, "이름": c.name, "설명": c.description,
                      "예시(원문 확인)": [f"{e} {'✅' if ok else '❌'}" for e, ok in checks], "확인 질문": c.check_question,
                      "근거 사례": c.case_ids, "이유": c.rationale, "근거 검색어": c.evidence_search_hint})
display(pd.DataFrame(cand_rows))
'''),
        md("## 3. 사람 승인 (`review_decisions.json`)"),
        code(r'''
decisions_path = APP_DIR / "notebooks" / "review_decisions.json"
decisions = json.loads(decisions_path.read_text(encoding="utf-8")) if decisions_path.exists() else {"approvals": []}
print(json.dumps(decisions, ensure_ascii=False, indent=1))
'''),
        md("## 4. 변경안 만들기 · 회귀 시험 (테스트셋 추출 재사용, 무비용)"),
        code(r'''
import yaml
rules_text = config.RULES_PATH.read_text(encoding="utf-8")
new_data, added = review.apply_approvals(yaml.safe_load(rules_text), draft, decisions, cases)
print("승인되어 변경안에 들어간 규칙:", [r["id"] for r in added] or "없음")
items = ev.load_items()
eval_cache = json.loads((RESULTS / "eval_cache_testset.json").read_text(encoding="utf-8"))
reg = review.regression(new_data, items, eval_cache)
print(json.dumps(reg, ensure_ascii=False, indent=1))
diff = review.rules_yaml_diff(rules_text, added)
(RESULTS / "rules_candidate.diff").write_text(diff or "# 승인된 후보 없음\n", encoding="utf-8")
summary = {"run_at": pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds"), "cases": len(cases), "expired_deleted": len(expired),
           "clusters": len(draft.clusters), "candidates": [c.suggested_id + " " + c.name for c in draft.candidates],
           "approved": [r["id"] for r in added], "regression": reg}
(RESULTS / "review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(diff or "변경안 없음")
'''),
    ]
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    return nb


if __name__ == "__main__":
    NB_DIR.mkdir(exist_ok=True)
    nbf.write(eval_notebook(), NB_DIR / "eval.ipynb")
    nbf.write(review_notebook(), NB_DIR / "rule_review.ipynb")
    print("written:", NB_DIR / "eval.ipynb", NB_DIR / "rule_review.ipynb")
