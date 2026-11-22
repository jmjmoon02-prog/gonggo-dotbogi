"""샘플·테스트셋·처리 흐름·확인 질문·화면 흐름 테스트 (API 호출 없음)."""
import os
from pathlib import Path

import pytest

from core import config
from core.links import manual_check_links
from core.masking import Masker, find_quote_spans
from core.pipeline import REPLY_HEADER, ExtractionUnavailable, FixtureExtractor, analyze
from core.questions import compose_message, select_questions, stop_advice
from core.rules_engine import load_rules
from core.samples import FLAGGED_GRADES, load_samples, load_testset, validate_testset

APP_FILE = str(Path(__file__).resolve().parent.parent / "app.py")


# ---------------------------------------------------------------------------
# 데모 샘플 → 의도한 등급
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sample", load_samples(), ids=lambda s: s.id)
def test_demo_samples_reach_expected_grade(sample):
    masker = Masker()
    ex = FixtureExtractor(sample.id)
    r1 = analyze(sample.text, sample.source_channel, masker, ex)
    assert r1.verdict.grade == sample.expected_grade, r1.verdict.reasons
    for h in r1.verdict.hits:  # 고정 추출값의 인용은 모두 원문에서 확인되어야 함
        if h.source == "ai":
            assert h.quote_verified, f"{sample.id} {h.rule_id}: {h.quote}"
    if sample.reply:
        r2 = analyze(sample.reply, sample.source_channel, masker, ex, previous=r1)
        assert r2.round_no == 2 and REPLY_HEADER in r2.masked_text
        assert r2.verdict.grade == sample.reply_expected_grade


def test_demo_set_covers_required_scenarios():
    grades = {s.id: (s.expected_grade, s.reply_expected_grade) for s in load_samples()}
    assert grades["demo_platform_normal"][0] == "green"
    assert grades["demo_telegram_cash"][0] == "red"
    assert grades["demo_brand_review"][0] == "orange"
    assert grades["demo_vague_dm"] == ("yellow", "red")  # 실제 AI 실측으로 확정(🟡 → 🔴)


def test_demo_samples_have_no_forbidden_word_or_real_contacts():
    for s in load_samples():
        assert "안전" not in s.text + (s.reply or "")
        r = Masker().mask(s.text)
        assert r.counts.get("phone", 0) == 0 and r.counts.get("account", 0) == 0


def test_fixture_missing_round_raises():
    with pytest.raises(ExtractionUnavailable):
        FixtureExtractor("demo_platform_normal")("x", "platform", 2)


# ---------------------------------------------------------------------------
# 테스트셋
# ---------------------------------------------------------------------------
def test_testset_is_valid_and_balanced():
    data = load_testset()
    assert validate_testset(data, set(load_rules().rules)) == []
    items = data["items"]
    assert len(items) == 53
    scam = [i for i in items if i["class"] == "scam"]
    normal = [i for i in items if i["class"] == "normal"]
    assert len(scam) == 33 and len(normal) == 20
    for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G12", "G13", "G14", "G15"):
        assert sum(i["group"] == g for i in items) == 3
    for g in ("N1", "N2", "N3", "N4", "N5"):
        assert sum(i["group"] == g for i in items) == 4
    for i in scam:
        assert set(i["acceptable_grades"]) <= FLAGGED_GRADES


def test_testset_contains_no_obvious_personal_data():
    for it in load_testset()["items"]:
        r = Masker().mask(it["text"])
        assert r.counts.get("phone", 0) == 0, it["id"]
        assert r.counts.get("rrn", 0) == 0, it["id"]
        assert r.counts.get("account", 0) == 0, it["id"]


# ---------------------------------------------------------------------------
# 확인 질문·링크·하이라이트
# ---------------------------------------------------------------------------
def _round(sample_id: str):
    s = next(x for x in load_samples() if x.id == sample_id)
    return analyze(s.text, s.source_channel, Masker(), FixtureExtractor(s.id))


def test_questions_for_white_include_red_flag_questions():
    r = _round("demo_vague_dm")
    qs = select_questions(r.verdict)
    assert 1 <= len(qs) <= 6
    assert any("돈이 들어가는" in q for q in qs)
    msg = compose_message(qs)
    assert msg.startswith("안녕하세요") and "1. " in msg
    assert stop_advice(r.verdict) is None


def test_ai_tailored_questions_follow_rule_questions():
    r = _round("demo_vague_dm")
    ids = [q["rule_id"] for q in r.verdict.check_questions]
    assert ids.index("S3") < ids.index("AI") < ids.index("GENERAL")
    qs = select_questions(r.verdict)
    assert any("월 200만 원" in q for q in qs)


def test_red_gets_stop_advice():
    r = _round("demo_telegram_cash")
    assert stop_advice(r.verdict)


def test_impersonation_question_first():
    r = _round("demo_brand_review")
    assert "공식" in select_questions(r.verdict)[0]


def test_manual_links_do_not_scrape_and_encode_query():
    links = manual_check_links("가상 제빵", None)
    assert links[0]["url"].startswith("https://search.naver.com/search.naver?query=")
    assert "%EA%B0%80%EC%83%81" in links[0]["url"]  # '가상' 인코딩
    assert any(l["url"] == "https://www.work24.go.kr" for l in links)


def test_find_quote_spans_tolerates_spacing():
    text = "업무: 고객님께 받은 현금을,  지정 장소에 전달"
    spans = find_quote_spans("고객님께 받은 현금을 지정 장소에 전달", text)
    assert spans and text[spans[0][0]:spans[0][1]].startswith("고객님께")
    assert find_quote_spans("없는 문장입니다", text) == []


# ---------------------------------------------------------------------------
# 화면 흐름 (Streamlit AppTest, 개발 모드 고정 추출값)
# ---------------------------------------------------------------------------
def _button(at, label):
    return next(b for b in at.button if b.label == label)


@pytest.fixture
def dev_mode(monkeypatch):
    monkeypatch.setenv("DEV_FIXTURES", "1")
    yield


def _markdown_text(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_app_vague_dm_two_rounds(dev_mode):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_FILE, default_timeout=30).run()
    assert not at.exception
    at.selectbox[0].select("④ 정보 부족 DM → 구인자 답변 후 재판정").run()
    _button(at, "샘플 불러오기").click().run()
    _button(at, "판정하기").click().run()
    assert not at.exception
    assert "주의" in _markdown_text(at)
    _button(at, "샘플 답변 넣기").click().run()
    _button(at, "답변 반영해 다시 판정").click().run()
    assert not at.exception
    text = _markdown_text(at)
    assert "1회차 🟡 주의 → 2회차 🔴 위험 신호 발견" in text


@pytest.mark.parametrize(
    "title, label",
    [
        ("① 정식 플랫폼 정상 공고 (매장 스태프)", "낮은 위험"),
        ("② 텔레그램 고액 알바 (현금 전달)", "위험"),
        ("③ 유명 쇼핑몰 사칭 리뷰 체험단 (문자)", "사칭 의심"),
        ("⑤ 해외 리조트 고수익 알바 (인스타 DM)", "위험"),
    ],
)
def test_app_demo_grades(dev_mode, title, label):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_FILE, default_timeout=30).run()
    at.selectbox[0].select(title).run()
    _button(at, "샘플 불러오기").click().run()
    _button(at, "판정하기").click().run()
    assert not at.exception
    assert f"{label}" in _markdown_text(at)
    assert "안전" not in _markdown_text(at)


def test_app_image_needs_consent_and_key():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_FILE, default_timeout=30).run()
    _button(at, "데모용 가상 이미지 사용").click().run()
    assert _button(at, "이미지에서 글자 읽기").disabled  # 개인정보 확인 전에는 못 보냄
    at.checkbox[0].check().run()
    btn = _button(at, "이미지에서 글자 읽기")
    assert not btn.disabled
    btn.click().run()
    assert not at.exception
    assert any("AI 키가 설정되지 않아" in w.value for w in at.warning)  # 테스트에는 키가 없다


def test_app_without_ai_shows_notice(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DEV_FIXTURES", raising=False)
    at = AppTest.from_file(APP_FILE, default_timeout=30).run()
    at.text_area[0].input("고액 알바 연락 주세요").run()
    _button(at, "판정하기").click().run()
    assert not at.exception
    assert any("AI 키가 설정되지 않아" in w.value for w in at.warning)


def test_app_fallback_shows_saved_sample_result_without_ai():
    """키가 없거나 사용량 초과일 때 '샘플 결과 화면 보기'로 미리 판독한 결과를 보여 준다(지적 12)."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_FILE, default_timeout=30).run()
    at.selectbox[0].select("④ 정보 부족 DM → 구인자 답변 후 재판정").run()
    _button(at, "샘플 불러오기").click().run()
    _button(at, "판정하기").click().run()
    assert any("샘플 결과" in w.value for w in at.warning)
    _button(at, "샘플 결과 화면 보기 (AI 호출 없음)").click().run()
    assert not at.exception
    assert any("미리 판독해 둔 샘플 결과" in i.value for i in at.info)
    first = _markdown_text(at)
    assert any(lbl in first for lbl in ("확인 필요", "주의"))  # 저장된 실제 AI 결과 기준 1회차는 ⚪ 또는 🟡
    _button(at, "샘플 답변 넣기").click().run()
    _button(at, "답변 반영해 다시 판정").click().run()
    assert "2회차 🔴 위험 신호 발견" in _markdown_text(at)


def test_app_shows_three_disclaimers_and_wake_notice():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_FILE, default_timeout=30).run()
    info = " ".join(i.value for i in at.info)
    assert "AI가 생성한 판정" in info and "법률 자문이 아닙니다" in info and "인증·제휴" in info
    captions = " ".join(c.value for c in at.caption)
    assert "Yes, get this app back up!" in captions
    assert "이름은 문맥 패턴으로 일부만" in captions
