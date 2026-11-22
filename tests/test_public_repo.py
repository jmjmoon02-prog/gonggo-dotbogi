"""공개 배포용 저장소 점검: app/ 만 공개되므로 비공개 문서를 참조하지 않고, 근거는 URL 로 따라갈 수 있어야 한다.

배포용 저장소는 app/ 폴더만 분리해 만든다(앱 실행 파일 = 저장소 루트의 app.py). 기획·결정 문서는 비공개로 남는다.
"""
import re
from pathlib import Path

import yaml

APP_DIR = Path(__file__).resolve().parent.parent
TEXT_EXT = {".py", ".md", ".yaml", ".yml", ".toml", ".txt", ".example", ".ipynb", ".json"}
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", ".ipynb_checkpoints"}
# 비공개 저장소에만 있는 문서 이름·상위 폴더 경로 (이 파일 자신은 검사에서 뺀다)
PRIVATE_REFS = re.compile(
    "|".join([
        "idea_" + "decision_log", "작업" + "지시서", "기획" + "서", "검토 " + "지적", "준비물_" + "체크리스트",
        "기획 " + "세션", "MVP " + "세션", r"\.\./", "kdt " + "공모전",
    ])
)


def _public_files():
    for p in APP_DIR.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(APP_DIR).parts):
            continue
        if p.is_file() and (p.suffix in TEXT_EXT or p.name.endswith(".example")) and p.name != Path(__file__).name:
            yield p


def test_no_reference_to_private_documents():
    hits = []
    for p in _public_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in PRIVATE_REFS.finditer(text):
            hits.append(f"{p.relative_to(APP_DIR)}: {m.group(0)}")
    assert hits == []


def test_every_evidence_id_has_url():
    data = yaml.safe_load((APP_DIR / "rules" / "rules.yaml").read_text(encoding="utf-8"))
    for eid, ev in data["evidence"].items():
        assert ev.get("url", "").startswith("https://"), eid
        assert ev.get("source") and ev.get("title"), eid


def test_no_secret_files_in_app():
    names = {p.name for p in APP_DIR.rglob("*") if ".venv" not in p.parts}
    assert "secrets.toml" not in names or not (APP_DIR / ".streamlit" / "secrets.toml").exists() or _ignored()


def _ignored() -> bool:
    gi = (APP_DIR / ".gitignore").read_text(encoding="utf-8")
    return ".streamlit/secrets.toml" in gi and ".env" in gi
