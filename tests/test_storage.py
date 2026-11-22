"""사례 저장 테스트. Hugging Face 에 실제로 올리지 않고 가짜 API·임시 폴더를 쓴다."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import storage
from core.masking import Masker
from core.pipeline import FixtureExtractor, analyze
from core.samples import get_sample
from core.schema import Facts, NpsCandidate, NpsResult, NtsResult

APP_FILE = str(Path(__file__).resolve().parent.parent / "app.py")
KST = timezone(timedelta(hours=9))


def _rounds(sample_id="demo_vague_dm", with_reply=True, extra_text=""):
    s = get_sample(sample_id)
    m = Masker()
    facts = Facts(nts=NtsResult(status="active", business_number="000-00-00000"),
                  nps=NpsResult(match="single", candidates=[NpsCandidate(name="가상상사", industry="도매업")]))
    r1 = analyze(s.text + extra_text, s.source_channel, m, FixtureExtractor(s.id), fact_checker=lambda e, b, p: facts)
    rounds = [r1]
    if with_reply and s.reply:
        rounds.append(analyze(s.reply, s.source_channel, m, FixtureExtractor(s.id), previous=r1,
                              fact_checker=lambda e, b, p: facts))
    return rounds


def test_case_contains_only_allowed_items():
    rounds = _rounds(extra_text="\n사업자등록번호 000-00-00000, 연락 010-1234-5678")
    case = storage.build_case(rounds, "feedback_scam", now=datetime(2026, 11, 23, 4, 0, tzinfo=KST))
    assert set(case) >= {"case_id", "masked_text", "extraction", "verdict", "created_at", "expires_at", "consent"}
    blob = json.dumps(case, ensure_ascii=False)
    assert "facts" not in case and "business_numbers" not in case
    assert "000-00-00000" not in blob and "[사업자번호]" in case["masked_text"]  # 사업자번호도 다시 가림
    assert "010-1234-5678" not in blob and "[전화번호1]" in case["masked_text"]
    assert "가상상사" not in blob and "도매업" not in blob  # 업체 조회 결과 비저장
    assert case["expires_at"] == "2027-02-21"  # 90일
    assert case["history"] == [{"round": 1, "grade": "yellow"}, {"round": 2, "grade": "red"}]
    assert case["consent"] is True


def test_unknown_trigger_rejected():
    with pytest.raises(ValueError):
        storage.build_case(_rounds(), "anything")


def test_hf_store_uploads_json_bytes_to_dataset_repo():
    calls = []

    class FakeApi:
        def upload_file(self, **kw):
            calls.append(kw)

    store = storage.HFDatasetStore("hf_test_token", "team/job-scam-cases", api=FakeApi())
    case = storage.build_case(_rounds(), "novel_suspect", now=datetime(2026, 11, 23, 4, 0, tzinfo=KST))
    path = store.save(case)
    kw = calls[0]
    assert path == f"cases/2026-11-23/{case['case_id']}.json" == kw["path_in_repo"]
    assert kw["repo_type"] == "dataset" and kw["repo_id"] == "team/job-scam-cases" and kw["token"] == "hf_test_token"
    assert json.loads(kw["path_or_fileobj"].decode("utf-8"))["case_id"] == case["case_id"]


def test_local_store_and_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.config, "APP_DIR", tmp_path)
    store = storage.LocalCaseStore(root=tmp_path / "cases")
    case = storage.build_case(_rounds(), "feedback_wrong")
    p = store.save(case)
    assert Path(p).exists() or (tmp_path / p).exists()
    assert not storage.expired(case)
    assert storage.expired(case, today=datetime.now(KST) + timedelta(days=storage.RETENTION_DAYS + 1))


def test_get_store_requires_token_and_repo(monkeypatch):
    assert storage.get_store() is None
    assert isinstance(storage.get_store(dev_mode=True), storage.LocalCaseStore)
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    monkeypatch.setenv("HF_DATASET_REPO", "team/repo")
    assert isinstance(storage.get_store(), storage.HFDatasetStore)


# ---------------------------------------------------------------------------
# 화면: 동의 전에는 저장 버튼이 꺼져 있다
# ---------------------------------------------------------------------------
def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_app_save_requires_consent(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DEV_FIXTURES", "1")  # 개발 모드 → 로컬 저장소
    monkeypatch.setattr(storage, "LOCAL_CASE_DIR", tmp_path / "cases")
    at = AppTest.from_file(APP_FILE, default_timeout=30).run()
    at.selectbox[0].select("② 텔레그램 고액 알바 (현금 전달)").run()
    _button(at, "샘플 불러오기").click().run()
    _button(at, "판정하기").click().run()
    assert _button(at, "실제로 사기였어요").disabled  # 기본은 동의 안 함
    consent = next(c for c in at.checkbox if "저장에 동의" in c.label)
    assert consent.value is False
    consent.check().run()
    btn = _button(at, "실제로 사기였어요")
    assert not btn.disabled
    btn.click().run()
    assert not at.exception
    assert any("저장했습니다" in s.value for s in at.success)
    saved = list((tmp_path / "cases").rglob("*.json"))
    assert len(saved) == 1
    assert "fastjob_demo" not in saved[0].read_text(encoding="utf-8")  # 메신저 ID 원문 없음
