"""같은 데모 샘플을 여러 번 실제로 판정해 등급·신호가 흔들리는지 본다(과금 호출, 사용자 승인 후 실행).

출력: 회차별 등급·걸린 규칙·토큰(입력/캐시 입력/출력/추론)·비용, 그리고 요약(등급 일치율, 규칙별 등장 횟수).
실행: (app 폴더에서) .venv/Scripts/python.exe scripts/stability_check.py [샘플ID] [반복 수]
기본: demo_vague_dm 5회 (1회차 + 2회차 = 회당 2호출)
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config  # noqa: E402
from core.extract import OpenAIExtractor, estimate_cost_usd, make_client  # noqa: E402
from core.masking import Masker  # noqa: E402
from core.pipeline import analyze  # noqa: E402
from core.samples import get_sample  # noqa: E402


def main() -> int:
    sample_id = sys.argv[1] if len(sys.argv) > 1 else "demo_vague_dm"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    s = get_sample(sample_id)
    client = make_client()
    print(f"model={config.model_id()} sample={sample_id} 반복={n} 기대: 1회차 {s.expected_grade}"
          + (f" / 2회차 {s.reply_expected_grade}" if s.reply else ""))
    results = {1: [], 2: []}
    costs = {1: [], 2: []}
    for i in range(1, n + 1):
        m = Masker()
        r1 = analyze(s.text, s.source_channel, m, OpenAIExtractor(client=client))
        runs = [r1]
        if s.reply:
            runs.append(analyze(s.reply, s.source_channel, m, OpenAIExtractor(client=client), previous=r1))
        for r in runs:
            u = r.usage or {}
            c = estimate_cost_usd(u) or 0.0
            costs[r.round_no].append((c, u))
            results[r.round_no].append((r.verdict.grade, tuple(sorted(r.verdict.matched_ids))))
            print(f"  #{i} {r.round_no}회차: {r.verdict.grade:<6} 규칙={','.join(sorted(r.verdict.matched_ids)) or '-':<28} "
                  f"in={u.get('input_tokens')} cached={u.get('cached_input_tokens')} out={u.get('output_tokens')} "
                  f"reasoning={u.get('reasoning_tokens')} ${c:.4f}")
    print("\n요약")
    for rnd, rows in results.items():
        if not rows:
            continue
        grades = Counter(g for g, _ in rows)
        rules = Counter(rule for _, ids in rows for rule in ids)
        cs = costs[rnd]
        avg = lambda key: sum((u.get(key) or 0) for _, u in cs) / len(cs)  # noqa: E731
        print(f"  {rnd}회차 등급 분포: {dict(grades)} | 규칙 등장 횟수(/{len(rows)}): {dict(rules)}")
        print(f"  {rnd}회차 평균: ${sum(c for c, _ in cs) / len(cs):.4f} | 입력 {avg('input_tokens'):,.0f} "
              f"(캐시 {avg('cached_input_tokens'):,.0f}) | 출력 {avg('output_tokens'):,.0f} (추론 {avg('reasoning_tokens'):,.0f})")
    total = sum(c for rnd in costs.values() for c, _ in rnd)
    print(f"  총 비용: ${total:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
