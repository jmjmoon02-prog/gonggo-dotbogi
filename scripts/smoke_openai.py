"""OpenAI 실제 호출 점검 (키를 넣은 뒤 1회 실행). 데모 샘플 5종(+2회차 답변)과 가상 이미지 1장.

- 가상 데이터만 보낸다. 키 값은 출력하지 않는다.
- 결과: 샘플별 기대 등급 vs 실제 등급, 인용 검증 통과율, 토큰·비용 추정.
실행: (app 폴더에서) .venv/Scripts/python.exe scripts/smoke_openai.py [--no-image] [--save-cache]
--save-cache: 실제 AI 추출 결과를 data/samples/cached_extractions.json 에 저장(사용량 초과 시 샘플 결과 화면용)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config  # noqa: E402
from core.extract import ImageInput, OpenAIExtractor, estimate_cost_usd, make_client, transcribe_image  # noqa: E402
from core.masking import Masker  # noqa: E402
from core.pipeline import ExtractionUnavailable, analyze  # noqa: E402
from core.samples import load_samples  # noqa: E402


def main() -> int:
    client = make_client()
    print(f"model={config.model_id()}")
    rows, total_cost, quotes, quotes_ok = [], 0.0, 0, 0

    def run(label, text, channel, masker, previous=None, expected=None):
        nonlocal total_cost, quotes, quotes_ok
        ex = OpenAIExtractor(client=client)
        t0 = time.time()
        try:
            r = analyze(text, channel, masker, ex, previous=previous)
        except ExtractionUnavailable as e:
            rows.append((label, expected, f"오류: {e}", "-", "-"))
            return None
        cost = estimate_cost_usd(r.usage) or 0.0
        total_cost += cost
        ai_hits = [h for h in r.verdict.hits if h.source == "ai"] + [a for a in r.verdict.anomalies if a.source == "ai"]
        quotes += len(ai_hits)
        quotes_ok += sum(1 for h in ai_hits if h.quote_verified)
        ok = "OK" if r.verdict.grade == expected else "다름"
        rows.append((label, expected, f"{r.verdict.grade} ({ok})", ",".join(r.verdict.matched_ids) or "-",
                     f"{time.time() - t0:.1f}s ${cost:.4f} in={r.usage and r.usage['input_tokens']} out={r.usage and r.usage['output_tokens']}"))
        return r

    cache: dict[str, dict] = {}
    cost_by_kind: dict[str, list[float]] = {"1회차 텍스트": [], "2회차": [], "이미지 포함": []}
    for s in load_samples():
        m = Masker()
        r1 = run(s.id, s.text, s.source_channel, m, expected=s.expected_grade)
        if r1 is not None:
            cache.setdefault(s.id, {})["round1"] = r1.extraction
            cost_by_kind["1회차 텍스트"].append(estimate_cost_usd(r1.usage) or 0.0)
        if s.reply and r1 is not None:
            r2 = run(s.id + " (2회차)", s.reply, s.source_channel, m, previous=r1, expected=s.reply_expected_grade)
            if r2 is not None:
                cache[s.id]["round2"] = r2.extraction
                cost_by_kind["2회차"].append(estimate_cost_usd(r2.usage) or 0.0)

    if "--no-image" not in sys.argv:
        img_path = config.SAMPLES_DIR / "demo_image_team_mission.png"
        try:
            text, usage = transcribe_image(ImageInput(img_path.read_bytes(), "png"), client=client)
            t_cost = estimate_cost_usd(usage) or 0.0
            total_cost += t_cost
            print("\n[이미지 글자 읽기]\n" + text + "\n")
            ri = run("demo_image (이미지→텍스트)", text, "sns_messenger", Masker(), expected="red")
            if ri is not None:
                cost_by_kind["이미지 포함"].append(t_cost + (estimate_cost_usd(ri.usage) or 0.0))
        except ExtractionUnavailable as e:
            rows.append(("demo_image", "red", f"오류: {e}", "-", "-"))

    print(f"\n{'샘플':<28} {'기대':<7} {'실제':<16} {'걸린 규칙':<22} 시간·비용")
    for row in rows:
        print(f"{row[0]:<28} {str(row[1]):<7} {row[2]:<16} {row[3]:<22} {row[4]}")
    if quotes:
        print(f"\n인용 검증 통과: {quotes_ok}/{quotes} ({quotes_ok / quotes:.0%})")
    print(f"총 비용 추정: ${total_cost:.4f}")
    for kind, costs in cost_by_kind.items():
        if costs:
            print(f"  판정 1건 평균 비용 [{kind}]: ${sum(costs) / len(costs):.4f} (n={len(costs)})")

    if "--save-cache" in sys.argv and cache:
        from datetime import datetime, timedelta, timezone

        from core.samples import save_cached_extractions

        stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
        path = save_cached_extractions(cache, config.model_id(), stamp)
        print(f"\n샘플 대체 화면용 저장: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
