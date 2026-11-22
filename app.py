"""Streamlit 진입점 (배포 시 Main file path: app/app.py).

화면 흐름: 소개·고지 → 입력(텍스트·출처 채널·샘플) → 결과(등급 → 신호 카드 → 업체 확인 →
확인 질문 → 법적 안내·신고처 → 직접 확인 링크) → 2회차(구인자 답변) → 피드백.
"""
from __future__ import annotations

import html
import io
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config  # noqa: E402
from core.extract import ImageInput, OpenAIExtractor, estimate_cost_usd, make_client, transcribe_image  # noqa: E402
from core.limits import DailyCounter, session_remaining, try_consume  # noqa: E402
from core.links import manual_check_links  # noqa: E402
from core.masking import Masker, find_quote_spans, normalize_for_match  # noqa: E402
from core.pipeline import (  # noqa: E402
    CachedSampleExtractor,
    ExtractionUnavailable,
    FixtureExtractor,
    RoundResult,
    analyze,
)
from core.questions import compose_message, select_questions, stop_advice  # noqa: E402
from core.rules_engine import Hit, load_rules  # noqa: E402
from core.samples import get_sample, load_samples  # noqa: E402

st.set_page_config(page_title=config.display_service_name(), page_icon="🔎", layout="centered")

RB = load_rules()
DEV_FIXTURES = config.get_setting("DEV_FIXTURES", "0") == "1"
HAS_AI_KEY = bool(config.get_secret("OPENAI_API_KEY"))
SESSION_LIMIT = config.session_call_limit()
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_SIDE = 2000
SAMPLE_IMAGE = config.SAMPLES_DIR / "demo_image_team_mission.png"
# docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app 'App hibernation' (2026-11-23 확인)
WAKE_NOTICE = (
    "💤 이 앱은 12시간 동안 방문이 없으면 잠듭니다. 잠든 화면이 나오면 "
    "'Yes, get this app back up!' 버튼을 누르고 잠시 기다려 주세요(누구나 깨울 수 있습니다)."
)


@st.cache_resource
def _daily_counter() -> DailyCounter:
    return DailyCounter(config.daily_call_limit())


@st.cache_resource
def _openai_client():
    return make_client()

GRADE_STYLE = {
    "red": ("#d93025", "rgba(217,48,37,0.10)"),
    "orange": ("#e8710a", "rgba(232,113,10,0.10)"),
    "yellow": ("#b06000", "rgba(249,171,0,0.14)"),
    "white": ("#5f6368", "rgba(128,134,139,0.10)"),
    "green": ("#188038", "rgba(24,128,56,0.10)"),
}
LEVEL_LABEL = {
    "red": "결정적",
    "yellow": "주의",
    "yellow_untrusted": "주의(신뢰 신호 없을 때)",
    "weak": "약한 신호",
    "none": "반영 안 함",
}
CHANNEL_LABEL = {
    "platform_message": "플랫폼 메시지", "phone_call": "전화", "sms": "문자", "kakao_personal": "카카오톡(개인)",
    "kakao_openchat": "카카오톡 오픈채팅", "telegram": "텔레그램", "line": "라인", "instagram_dm": "인스타그램 DM",
    "other_messenger": "기타 메신저", "email": "이메일", "external_link": "외부 링크", "in_person": "대면",
    "unknown": "알 수 없음",
}
MASK_LABEL = {"rrn": "주민번호", "card": "카드번호", "phone": "전화번호", "account": "계좌번호",
              "email": "이메일", "messenger_id": "메신저 ID", "name": "이름"}

st.markdown(
    """
<style>
.grade-box {border-radius: 12px; padding: 18px 20px; margin: 8px 0 14px 0; border: 2px solid;}
.grade-title {font-size: 1.6rem; font-weight: 700; margin: 0;}
.grade-sub {margin: 6px 0 0 0; font-size: 0.95rem;}
.quote-box {padding: 10px 12px; border-radius: 8px; background: rgba(128,134,139,0.08);
            white-space: pre-wrap; line-height: 1.6; font-size: 0.95rem;}
.quote-box mark {background: rgba(249,171,0,0.45); padding: 0 2px; border-radius: 3px;}
.tag {display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.8rem; margin-right: 4px;
      border: 1px solid rgba(128,134,139,0.5);}
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 상태
# ---------------------------------------------------------------------------
def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("masker", Masker())
    ss.setdefault("input_text", "")
    ss.setdefault("reply_text", "")
    ss.setdefault("source_channel", "sns_messenger")
    ss.setdefault("sample_id", None)
    ss.setdefault("rounds", [])  # list[RoundResult]
    ss.setdefault("error", None)
    ss.setdefault("image_error", None)
    ss.setdefault("pending", None)  # 다음 실행에서 처리할 작업: 1, 2, "transcribe"
    ss.setdefault("sample_image", False)
    ss.setdefault("error_kind", None)
    ss.setdefault("fallback_mode", False)  # AI 대신 미리 저장한 샘플 결과를 보여 주는 중


def _reset_results() -> None:
    st.session_state["masker"] = Masker()
    st.session_state["rounds"] = []
    st.session_state["reply_text"] = ""
    st.session_state["error"] = None
    st.session_state["error_kind"] = None


def _request(action) -> None:
    st.session_state["pending"] = action


def _load_sample(fallback: bool = False) -> None:
    sample = next((s for s in load_samples() if s.title == st.session_state.get("sample_pick")), None)
    if sample is None:
        sample = load_samples()[0]
    st.session_state["input_text"] = sample.text
    st.session_state["source_channel"] = sample.source_channel
    st.session_state["sample_id"] = sample.id
    _reset_results()
    st.session_state["fallback_mode"] = fallback


def _start_fallback() -> None:
    """AI 사용량 초과·키 문제 시: 선택한 데모 샘플을 미리 저장한 결과로 보여 준다(AI 호출 없음)."""
    _load_sample(fallback=True)
    st.session_state["pending"] = 1


def _load_sample_reply() -> None:
    sample = get_sample(st.session_state.get("sample_id") or "")
    if sample and sample.reply:
        st.session_state["reply_text"] = sample.reply


def _same_text(a: str, b: str | None) -> bool:
    return b is not None and normalize_for_match(a) == normalize_for_match(b)


def _consume_ai_call() -> None:
    ok, msg = try_consume(st.session_state, SESSION_LIMIT, _daily_counter())
    if not ok:
        raise ExtractionUnavailable(msg + " 아래에서 미리 판독해 둔 샘플 결과를 볼 수 있습니다.", kind="limit")


def _choose_extractor(round_no: int):
    """샘플 문장 그대로 + (개발 모드 → 고정 추출값 / 대체 모드 → 저장된 결과). 그 밖에는 OpenAI 추출(호출 상한 적용)."""
    ss = st.session_state
    sample = get_sample(ss.get("sample_id") or "")
    if sample is not None and (DEV_FIXTURES or ss.get("fallback_mode")):
        text_ok = _same_text(ss["input_text"], sample.text)
        reply_ok = round_no == 1 or _same_text(ss["reply_text"], sample.reply)
        if text_ok and reply_ok:
            return CachedSampleExtractor(sample.id) if ss.get("fallback_mode") else FixtureExtractor(sample.id)
    if not HAS_AI_KEY:
        raise ExtractionUnavailable(
            "AI 키가 설정되지 않아 실시간 AI 판독을 할 수 없습니다. 아래에서 미리 판독해 둔 샘플 결과를 볼 수 있습니다.",
            kind="config",
        )
    _consume_ai_call()
    return OpenAIExtractor(client=_openai_client(), rulebook=RB)


def _run(round_no: int) -> None:
    ss = st.session_state
    ss["error"] = None
    try:
        if round_no == 1:
            text = ss["input_text"].strip()
            if not text:
                ss["error"] = "공고 내용을 붙여넣어 주세요."
                return
            if len(text) > config.MAX_INPUT_CHARS:
                ss["error"] = f"입력은 {config.MAX_INPUT_CHARS:,}자까지 가능합니다."
                return
            extractor = _choose_extractor(1)
            ss["masker"] = Masker()
            ss["rounds"] = [analyze(text, ss["source_channel"], ss["masker"], extractor)]
            ss["reply_text"] = ""  # 답변 칸은 결과 아래에 그려지므로 아직 위젯 생성 전이다
        else:
            reply = ss["reply_text"].strip()
            if not reply:
                ss["error"] = "구인자 답변을 붙여넣어 주세요."
                return
            extractor = _choose_extractor(2)
            prev: RoundResult = ss["rounds"][0]
            ss["rounds"] = [prev, analyze(reply, prev.source_channel, ss["masker"], extractor, previous=prev)]
    except ExtractionUnavailable as e:
        ss["error"] = str(e)
        ss["error_kind"] = e.kind


FALLBACK_KINDS = {"quota", "limit", "config"}


def _error_box() -> None:
    ss = st.session_state
    if not ss["error"]:
        return
    st.warning(ss["error"])
    if ss.get("error_kind") in FALLBACK_KINDS:
        st.button("샘플 결과 화면 보기 (AI 호출 없음)", on_click=_start_fallback, key=f"fallback_{len(ss['rounds'])}",
                  help="위 목록에서 고른 데모 샘플을, 미리 판독해 둔 결과로 보여 줍니다.")


# ---------------------------------------------------------------------------
# 이미지 (사용자가 '개인정보를 가렸다'고 확인한 경우에만 AI 로 글자 읽기)
# ---------------------------------------------------------------------------
def _prepare_image(raw: bytes) -> ImageInput:
    """메타데이터(EXIF 위치 등)를 지우고 크기를 줄여 다시 저장한다."""
    from PIL import Image

    if len(raw) > MAX_IMAGE_BYTES:
        raise ExtractionUnavailable("이미지는 5MB 이하만 올릴 수 있습니다.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.seek(0)
        img = img.convert("RGB")
    except Exception as exc:
        raise ExtractionUnavailable("이미지를 읽을 수 없습니다. PNG·JPG·WEBP 파일을 올려 주세요.") from exc
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return ImageInput(data=buf.getvalue(), ext="png", detail="high")


def _current_image_bytes() -> bytes | None:
    up = st.session_state.get("image_upload")
    if up is not None:
        return up.getvalue()
    if st.session_state.get("sample_image") and SAMPLE_IMAGE.exists():
        return SAMPLE_IMAGE.read_bytes()
    return None


def _transcribe() -> None:
    ss = st.session_state
    ss["image_error"] = None
    try:
        raw = _current_image_bytes()
        if raw is None:
            raise ExtractionUnavailable("이미지를 먼저 올려 주세요.")
        if not ss.get("image_consent"):
            raise ExtractionUnavailable("이미지 속 개인정보를 가렸는지 먼저 확인해 주세요.")
        if not HAS_AI_KEY:
            raise ExtractionUnavailable("AI 키가 설정되지 않아 이미지 글자 읽기를 할 수 없습니다.")
        image = _prepare_image(raw)
        _consume_ai_call()
        text, _usage = transcribe_image(image, client=_openai_client())
        if not text:
            raise ExtractionUnavailable("이미지에서 글자를 찾지 못했습니다.")
        ss["input_text"] = text[: config.MAX_INPUT_CHARS]
        ss["sample_id"] = None
        _reset_results()
    except ExtractionUnavailable as e:
        ss["image_error"] = str(e)


def _use_sample_image() -> None:
    st.session_state["sample_image"] = True


# ---------------------------------------------------------------------------
# 그리기 도우미
# ---------------------------------------------------------------------------
def _highlight(text: str, quotes: list[str | None]) -> str:
    spans: list[tuple[int, int]] = []
    for q in quotes:
        spans.extend(find_quote_spans(q, text))
    spans.sort()
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    out, pos = [], 0
    for s, e in merged:
        out.append(html.escape(text[pos:s]))
        out.append(f"<mark>{html.escape(text[s:e])}</mark>")
        pos = e
    out.append(html.escape(text[pos:]))
    return f'<div class="quote-box">{"".join(out)}</div>'


def _evidence_links(ids) -> str:
    parts = []
    for eid in ids:
        ev = RB.evidence_link(eid)
        if ev:
            parts.append(f"[{eid}]({ev['url']} \"{ev['title']}\")")
    return " · ".join(parts)


def _grade_box(r: RoundResult) -> None:
    v = r.verdict
    fg, bg = GRADE_STYLE[v.grade]
    novel = ' <span class="tag">신종 의심</span>' if v.novel_suspect else ""
    st.markdown(
        f'<div class="grade-box" style="border-color:{fg}; background:{bg};">'
        f'<p class="grade-title" style="color:{fg};">{v.emoji} {html.escape(v.label)}{novel}</p>'
        f'<p class="grade-sub">위험 신호 안내이며 사기 여부를 확정하지 않습니다 · 규칙 v{html.escape(v.rules_version)}'
        f" · {r.round_no}회차</p></div>",
        unsafe_allow_html=True,
    )
    for reason in v.reasons:
        st.markdown(f"- {reason}")


def _hit_card(h: Hit, masked_text: str) -> None:
    with st.container(border=True):
        level = LEVEL_LABEL.get(h.level, h.level)
        st.markdown(f"**{h.name}**  \n<span class='tag'>{level}</span><span class='tag'>{h.rule_id}</span>",
                    unsafe_allow_html=True)
        if h.quote:
            if h.quote_verified is False:
                st.caption("⚠️ 이 근거 문장은 원문에서 확인되지 않아 한 단계 낮춰 반영했습니다.")
            st.markdown(_highlight(h.quote, []), unsafe_allow_html=True)
        if h.explanation:
            st.markdown(h.explanation)
        if h.guidance:
            st.markdown(f"👉 {h.guidance}")
        links = _evidence_links(h.evidence_ids)
        if links:
            st.caption(f"근거: {links}")


def _facts_section(r: RoundResult) -> None:
    st.subheader("업체 확인 결과")
    ex, f = r.extraction, r.facts
    c1, c2 = st.columns(2)
    c1.markdown(f"**공고 속 업체명**: {ex.company.name or '없음'}")
    c1.markdown(f"**내세운 브랜드**: {ex.company.brand_name or '없음'}")
    if r.business_numbers:
        bn_txt = ", ".join(f"{b.formatted}{'' if b.checksum_ok else ' (형식 오류)'}" for b in r.business_numbers)
    else:
        bn_txt = "없음"
    c2.markdown(f"**사업자등록번호**: {bn_txt}")
    c2.markdown(f"**연락 경로**: {', '.join(CHANNEL_LABEL.get(c, c) for c in ex.contact.channels) or '알 수 없음'}")
    status_text = {
        "not_checked": "조회 안 함 (공공 API 연결 전)", "error": "조회 실패", "disabled": "기능 꺼짐",
        "active": "계속사업자", "suspended": "휴업", "closed": "폐업", "not_registered": "국세청 미등록 번호",
        "single": "1곳 확인", "multiple": "여러 곳(후보 선택 필요)", "none": "찾지 못함(확인 불가, 위험 아님)",
        "match": "공식 공고 일치", "mismatch": "공식 공고와 불일치",
    }
    rows = [
        ("국세청 사업자 상태", f.nts.status, f.nts.checked_at),
        ("국민연금 가입 사업장", f.nps.match, f.nps.checked_at),
        ("워크넷 공식 채용정보", f.worknet.match, f.worknet.checked_at),
    ]
    st.table(hide_index=True, data=[{"확인 항목": n, "결과": status_text.get(s, s), "조회 시각": t or "-"} for n, s, t in rows])
    if r.verdict.hourly_wage:
        ratio = r.verdict.hourly_wage / config.MINIMUM_WAGE_HOURLY
        st.caption(f"시급 환산 약 {r.verdict.hourly_wage:,.0f}원 · {config.MINIMUM_WAGE_YEAR} 최저임금 "
                   f"{config.MINIMUM_WAGE_HOURLY:,}원의 {ratio:.1f}배 ([출처]({config.MINIMUM_WAGE_URL}))")
    for info in r.verdict.info_needed:
        st.markdown(f"- {info}")


def _value_flow_section(r: RoundResult) -> None:
    vf = r.extraction.value_flow
    groups = [
        ("근로자가 내야 하는 것", vf.worker_pays), ("근로자가 받는 것", vf.worker_receives),
        ("근로자를 거쳐 가는 것", vf.passes_through_worker), ("요구하는 행동", vf.required_actions),
        ("근로자가 잃는 통제", vf.control_loss),
    ]
    rows = [{"구분": name, "내용": it.item, "근거 문장": it.quote} for name, items in groups for it in items]
    if rows:
        st.table(rows, hide_index=True)
    else:
        st.caption("추출된 가치 흐름이 없습니다.")
    if vf.hiring_process:
        st.caption(f"연락·채용 방식: {vf.hiring_process}")


def _result_section(r: RoundResult) -> None:
    v = r.verdict
    _grade_box(r)

    if v.labor_flags:
        for f in v.labor_flags:
            st.warning(f"**{f.name}** — {f.explanation}  \n{f.guidance or ''}")

    risk_hits = [h for h in v.hits if h.level != "none" and h.tier != "X"]
    if v.impersonation or risk_hits or v.anomalies:
        st.subheader("걸린 신호")
        st.markdown(_highlight(r.masked_text, [h.quote for h in risk_hits + v.anomalies]), unsafe_allow_html=True)
        st.caption("노란색은 AI가 근거로 인용하고 코드로 원문에서 확인한 문장입니다. 개인정보는 [전화번호1]처럼 가려져 있습니다.")
        if v.impersonation:
            _hit_card(v.impersonation, r.masked_text)
        for h in risk_hits:
            _hit_card(h, r.masked_text)
        for a in v.anomalies:
            _hit_card(a, r.masked_text)
    if v.trust:
        st.markdown("**신뢰 신호**: " + ", ".join(f"{t.name}" for t in v.trust))

    _facts_section(r)

    st.subheader("구인자에게 물어볼 확인 질문")
    advice = stop_advice(v)
    questions = select_questions(v)
    if advice:
        st.error(advice)
    if questions:
        msg = compose_message(questions)
        ai_n = sum(1 for q in v.check_questions if q["rule_id"] == "AI" and q["question"] in questions)
        if ai_n:
            st.caption(f"질문 {len(questions)}개 중 {ai_n}개는 AI가 이 공고에 맞춰 만든 질문이고, 나머지는 공식 자료 기반 규칙의 질문입니다.")
        if advice:
            with st.expander("그래도 확인하고 싶다면: 질문 보기"):
                st.code(msg, language=None)
        else:
            st.code(msg, language=None)
            st.caption("오른쪽 위 복사 버튼으로 복사해 보내고, 받은 답변을 아래 '2회차'에 붙여넣으세요.")
    else:
        st.caption("추가로 물어볼 질문이 없습니다. 근로계약서는 꼭 확인하세요.")

    if v.legal_notes:
        st.subheader("법적 결과 안내")
        for n in v.legal_notes:
            st.markdown(f"- **{n['name']}**: {n['text']}")
    if v.report_contacts:
        st.subheader("신고·상담처")
        for c in v.report_contacts:
            num = f" **{c['number']}**" if c.get("number") else ""
            act = f" — {c['action']}" if c.get("action") else ""
            st.markdown(f"- {c['name']}{num}{act} <sub>({_evidence_links(c.get('evidence_ids', []))})</sub>",
                        unsafe_allow_html=True)

    st.subheader("직접 확인해 볼 곳")
    st.caption("민간 채용 사이트는 자동으로 조회하지 않습니다. 직접 열어서 확인해 주세요.")
    for link in manual_check_links(r.extraction.company.name, r.extraction.company.brand_name):
        st.markdown(f"- [{link['name']}]({link['url']}) — {link['hint']}")

    with st.expander("AI가 읽어낸 정보 (가치 흐름)"):
        _value_flow_section(r)
        if r.extraction.other_anomalies:
            st.markdown("**기타 이상 신호(판정에는 쓰지 않음)**")
            for a in r.extraction.other_anomalies:
                st.markdown(f"- {a.description}")
    with st.expander("AI에 보낸 내용 (마스킹 후)"):
        counts = ", ".join(f"{MASK_LABEL.get(k, k)} {n}개" for k, n in r.mask_counts.items()) or "가린 항목 없음"
        st.caption(f"자동으로 가린 항목: {counts}")
        st.text(r.masked_text)
        if v.candidate_hits:
            st.caption("검토 중인 후보 규칙에 걸림(판정 미반영): " + ", ".join(h.rule_id for h in v.candidate_hits))
    cost = estimate_cost_usd(r.usage)
    cost_txt = f" · 토큰 입력 {r.usage['input_tokens']:,} / 출력 {r.usage['output_tokens']:,} (약 ${cost:.4f})" if cost else ""
    st.caption(f"AI 생성: 정보 추출·설명은 {r.extractor_name}가 만들었고, 등급은 공개 규칙(rules.yaml v{v.rules_version})으로 "
               f"계산했습니다 · {r.created_at}{cost_txt}")


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
_init_state()

with st.sidebar:
    st.header(config.display_service_name())
    st.caption(config.SERVICE_TAGLINE)
    st.subheader("꼭 기억할 원칙")
    for p in RB.principles:
        src = _evidence_links(p["evidence_ids"])
        if p.get("evidence_note"):
            src = f"{src} {p['evidence_note']}"
        st.markdown(f"- {p['text']} <sub>({src})</sub>", unsafe_allow_html=True)
    st.subheader("이렇게 판정합니다")
    st.markdown(
        "1. 전화번호·계좌·이름 등을 자동으로 가립니다\n"
        "2. AI가 업체·급여·연락 경로·돈의 흐름과 위험 신호를 근거 문장과 함께 뽑습니다\n"
        "3. 근거 문장이 원문에 실제로 있는지 코드로 확인합니다\n"
        "4. 공공 API로 업체를 확인합니다\n"
        "5. 공개된 규칙으로 등급을 정합니다"
    )
    if DEV_FIXTURES:
        st.warning("개발 모드: 샘플은 사람이 적어 둔 고정 추출값을 씁니다(AI 호출 없음).")
    st.subheader("AI 사용")
    st.caption(f"모델: {config.model_id()} (OpenAI) · AI는 정보 추출·설명만, 등급은 공개 규칙으로 계산")
    if HAS_AI_KEY:
        st.caption(f"남은 AI 호출: 이 화면 {session_remaining(st.session_state, SESSION_LIMIT)}회 · "
                   f"오늘 전체 {_daily_counter().remaining()}회")
    else:
        st.caption("AI 키가 설정되지 않았습니다.")
    st.divider()
    st.caption(WAKE_NOTICE)

st.title(config.display_service_name())
st.markdown(config.SERVICE_TAGLINE)
st.info(
    "- **AI가 생성한 판정이며 참고용입니다.** 위험 신호를 안내할 뿐 업체나 사기 여부를 단정하지 않습니다. "
    "가장 좋은 결과도 '낮은 위험(확인 권장)'이며, 근로계약서는 항상 직접 확인하세요.\n"
    "- **법률 자문이 아닙니다.**\n"
    "- **공공데이터를 활용한 개인 프로젝트이며, 어떤 기관의 인증·제휴도 받지 않았습니다.**",
    icon="ℹ️",
)

st.subheader("1. 받은 공고·메시지 붙여넣기")
col_s, col_b = st.columns([3, 1])
col_s.selectbox("데모용 가상 공고", [s.title for s in load_samples()], key="sample_pick", label_visibility="collapsed")
col_b.button("샘플 불러오기", on_click=_load_sample, width="stretch")

with st.expander("캡처 이미지로 입력하기"):
    st.caption(
        "⚠️ 이미지는 자동으로 가릴 수 없습니다. 이미지 속 전화번호·계좌번호·이름 등을 가린 뒤 올려 주세요. "
        "**아래 '가렸습니다' 확인에 체크해야만 이미지를 AI로 보냅니다.** "
        "AI가 이미지 속 글자만 읽어 아래 입력 칸에 넣고, 판정 전에 다시 자동 마스킹합니다. "
        "이미지 메타데이터(위치 등)는 지우고 보냅니다."
    )
    st.file_uploader("캡처 이미지", type=["png", "jpg", "jpeg", "webp", "gif"], key="image_upload")
    if SAMPLE_IMAGE.exists():
        st.button("데모용 가상 이미지 사용", on_click=_use_sample_image)
    preview = _current_image_bytes()
    if preview:
        st.image(preview, caption="AI로 보낼 이미지", width=320)
    st.checkbox("이미지 속 개인정보를 가렸거나, 가상으로 만든 이미지입니다", key="image_consent")
    st.button("이미지에서 글자 읽기", on_click=_request, args=("transcribe",),
              disabled=not (preview and st.session_state.get("image_consent")))
    if st.session_state["pending"] == "transcribe":
        st.session_state["pending"] = None
        with st.spinner("AI가 이미지 속 글자를 읽는 중입니다…"):
            _transcribe()
    if st.session_state["image_error"]:
        st.warning(st.session_state["image_error"])

st.text_area(
    "공고 내용", key="input_text", height=180, max_chars=config.MAX_INPUT_CHARS,
    placeholder="SNS·메신저·문자로 받은 알바 공고나 DM을 그대로 붙여넣으세요.",
)
st.caption(
    "AI로 보내기 전에 전화번호·계좌·카드·주민번호·이메일·메신저 ID를 자동으로 가립니다. "
    "**이름은 문맥 패턴으로 일부만 가리므로 누락될 수 있습니다** — 가능하면 이름은 지우고 붙여넣어 주세요."
)
st.radio("어디서 받았나요?", list(config.SOURCE_CHANNELS), key="source_channel",
         format_func=lambda k: config.SOURCE_CHANNELS[k], horizontal=False)
st.button("판정하기", type="primary", on_click=_request, args=(1,), width="stretch")

if st.session_state["pending"] in (1, 2):
    action = st.session_state["pending"]
    st.session_state["pending"] = None
    with st.spinner("AI가 공고를 읽고, 규칙으로 판정하는 중입니다… (10~30초)"):
        _run(action)

if not st.session_state["rounds"]:
    _error_box()

rounds: list[RoundResult] = st.session_state["rounds"]
if rounds:
    st.divider()
    st.subheader("2. 판정 결과")
    if st.session_state.get("fallback_mode"):
        st.info("실시간 AI 대신 **미리 판독해 둔 샘플 결과**를 보여 주고 있습니다(AI 호출 없음). "
                f"추출 출처: {rounds[-1].extractor_name}")
    if len(rounds) > 1:
        a, b = rounds[0].verdict, rounds[-1].verdict
        st.markdown(f"**1회차 {a.emoji} {a.label} → 2회차 {b.emoji} {b.label}** (구인자 답변 반영)")
        _result_section(rounds[-1])
        with st.expander("1회차 결과 다시 보기"):
            _result_section(rounds[0])
    else:
        _result_section(rounds[0])

    st.divider()
    st.subheader("3. 구인자 답변으로 다시 판정 (2회차)")
    st.caption("확인 질문을 보내고 받은 답변을 붙여넣으면, 처음 공고와 함께 다시 판정합니다.")
    sample = get_sample(st.session_state.get("sample_id") or "")
    if sample and sample.reply:
        st.button("샘플 답변 넣기", on_click=_load_sample_reply)
    st.text_area("구인자 답변", key="reply_text", height=120, max_chars=config.MAX_INPUT_CHARS)
    st.button("답변 반영해 다시 판정", on_click=_request, args=(2,))
    _error_box()

    st.divider()
    st.subheader("판정이 맞았나요?")
    c1, c2 = st.columns(2)
    c1.button("판정이 틀렸어요", disabled=True, width="stretch", help="사례 저장 기능은 다음 단계에서 연결됩니다")
    c2.button("실제로 사기였어요", disabled=True, width="stretch", help="사례 저장 기능은 다음 단계에서 연결됩니다")
    st.caption("누르면 개인정보를 가린 내용과 판정 결과만 저장해 규칙 검토에 씁니다. 피드백만으로 규칙이 바뀌지는 않습니다.")

st.divider()
st.caption(WAKE_NOTICE)
st.caption(
    f"{config.display_service_name()} · {config.TEAM_NAME} · 2026 대한민국 청년 CAREER FAIR AI 해커톤 출품 프로토타입 · "
    "공공데이터를 활용한 개인 프로젝트이며 기관의 인증·제휴가 아닙니다 · 법률 자문이 아닙니다 · "
    "공고 본문은 판정 대상 데이터로만 다루며, 본문 속 지시는 따르지 않습니다."
)
