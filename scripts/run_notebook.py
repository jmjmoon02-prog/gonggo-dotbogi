"""노트북을 실행해 출력까지 저장한다(실행 기록). 키는 app/.env 에서 읽는다.

실행: (app 폴더에서) .venv/Scripts/python.exe scripts/run_notebook.py notebooks/eval.ipynb
"""
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient


def redact_local_paths(nb, app_dir: Path) -> None:
    """출력에 남은 이 PC의 경로(사용자 폴더 이름 포함)를 지운다. 공개 저장소에 올라가는 실행 기록이므로."""
    pairs = []
    for raw, label in ((str(app_dir), "<app>"), (str(Path.home()), "~")):
        pairs += [(raw, label), (raw.replace("\\", "/"), label)]
    pairs.sort(key=lambda p: len(p[0]), reverse=True)  # 긴 경로(app)부터 바꾼다

    def clean(s: str) -> str:
        for raw, label in pairs:
            s = s.replace(raw, label)
        return s

    for cell in nb.cells:
        for out in cell.get("outputs", []):
            if isinstance(out.get("text"), str):
                out["text"] = clean(out["text"])
            for mime, val in list(out.get("data", {}).items()):
                if isinstance(val, str):
                    out["data"][mime] = clean(val)


def main() -> int:
    path = Path(sys.argv[1]).resolve()
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(nb, timeout=1800, kernel_name="python3", resources={"metadata": {"path": str(path.parent)}})
    try:
        client.execute()
    finally:
        redact_local_paths(nb, path.parent.parent)
        nbformat.write(nb, path)  # 실패해도 거기까지의 출력은 남긴다
    print("executed:", path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
