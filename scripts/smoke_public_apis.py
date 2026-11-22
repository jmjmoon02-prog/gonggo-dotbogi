"""공공 API 작동 점검 (키를 넣은 뒤 1회 실행, 무료). 키 값은 출력하지 않는다.

- 국세청: 존재할 수 없는 번호 000-00-00000 → '국세청 미등록'이 나오면 API·키 정상
- 국민연금: 명세 페이지의 예시 사업장명(삼성전자로지텍주식회사)으로 조회
- 고용24 채용정보: 명세 예시 키워드('개발자')로 목록 조회 → 건수가 나오면 정상
실행: (app 폴더에서) .venv/Scripts/python.exe scripts/smoke_public_apis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from core.masking import BusinessNumber  # noqa: E402
from core.verify_apis import WORK24_URL, _key, check_nps, check_nts, parse_work24  # noqa: E402


def main() -> int:
    s = requests.Session()
    data_key, w24_key = _key("DATA_GO_KR_SERVICE_KEY"), _key("WORK24_AUTH_KEY")
    print(f"data.go.kr 키: {'있음' if data_key else '없음'} / 고용24 키: {'있음' if w24_key else '없음'}")

    nts = check_nts(s, data_key, BusinessNumber("0000000000", True))
    print(f"[국세청] status={nts.status} message={nts.message}")

    nps = check_nps(s, data_key, "삼성전자로지텍주식회사", None, None)
    print(f"[국민연금] match={nps.match} message={nps.message}")
    for c in nps.candidates[:3]:
        print(f"   - {c.name} | {c.address} | 업종={c.industry} | 가입자={c.members} | {c.status}")

    if w24_key:
        try:
            r = s.get(WORK24_URL, params={"authKey": w24_key, "callTp": "L", "returnType": "XML", "startPage": 1,
                                          "display": 3, "keyword": "개발자"}, timeout=10)
            print(f"[고용24] HTTP {r.status_code}")
            total, rows = parse_work24(r.text)
            print(f"[고용24] total={total}")
            for row in rows[:3]:
                print(f"   - {row['company']} | {row['title']} | {row['region']} | 업종={row['indTpNm']}")
        except Exception as e:
            print(f"[고용24] 실패: {type(e).__name__}: {str(e)[:200]}")
    else:
        print("[고용24] 키 없음 → 앱에서는 공식 공고 대조만 생략하고 동작")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
