"""Hugging Face 사례 저장소 점검 (토큰을 넣은 뒤 1회 실행). 파일을 올리지 않고 권한만 확인한다. 토큰 값은 출력하지 않는다.

- HfApi.auth_check(repo_id, repo_type="dataset", token=..., write=True): 쓰기 권한 확인 (huggingface_hub 2.4.0)
- HfApi.repo_info(...).private: 비공개 저장소인지 확인
실행: (app 폴더에서) .venv/Scripts/python.exe scripts/smoke_hf.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from huggingface_hub import HfApi  # noqa: E402

from core import config  # noqa: E402


def main() -> int:
    token, repo = config.get_secret("HF_TOKEN"), config.get_secret("HF_DATASET_REPO")
    print(f"HF_TOKEN: {'있음' if token else '없음'} / HF_DATASET_REPO: {repo or '없음'}")
    if not (token and repo):
        return 1
    api = HfApi()
    try:
        info = api.repo_info(repo, repo_type="dataset", token=token)
        print(f"저장소 확인: {repo} | 비공개={getattr(info, 'private', '?')}")
    except Exception as e:
        print(f"저장소 확인 실패: {type(e).__name__}: {str(e)[:200]}")
        return 1
    try:
        api.auth_check(repo, repo_type="dataset", token=token, write=True)
        print("쓰기 권한: 있음")
    except Exception as e:
        print(f"쓰기 권한 확인 실패: {type(e).__name__}: {str(e)[:200]}")
        return 1
    files = api.list_repo_files(repo, repo_type="dataset", token=token)
    print(f"현재 파일 수: {len(files)} (사례: {sum(f.startswith('cases/') for f in files)}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
