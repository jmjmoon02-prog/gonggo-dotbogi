"""AI 호출 전 개인정보 마스킹 + 인용 검증용 텍스트 정규화.

원칙
- 외부 AI 로 보내기 전에 전화번호·계좌번호·카드번호·주민등록번호·이메일·메신저 ID·사람 이름을
  토큰([전화번호1] 등)으로 바꾼다. 원래 값은 저장하지 않는다(복원 기능 없음).
- 같은 세션 안에서 같은 값은 같은 토큰이 되도록, 원래 값 대신 세션별 무작위 키로 만든 해시만 기억한다.
- 사업자등록번호(000-00-00000)는 개인정보가 아니라 공개 조회 대상이므로 마스킹하지 않고,
  국세청·국민연금 조회용으로 따로 뽑아 둔다.
- 패턴 기반이라 완벽하지 않다. 시연·테스트는 가상 데이터만 쓴다(대회 규정).
"""
from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 전처리: 전각 문자·하이픈 변형·보이지 않는 문자 정리
# ---------------------------------------------------------------------------
_ZERO_WIDTH = re.compile(r"[​-‏⁠﻿­]")
_DASHES = re.compile(r"[‐-―−﹘﹣－]")


def _fullwidth_to_ascii(text: str) -> str:
    # 전각 ASCII(！~～)만 반각으로. 한글 호환 자모(ㅌ 등)는 건드리지 않는다.
    return "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in text)


def preprocess(text: str) -> str:
    text = _ZERO_WIDTH.sub("", text)
    text = _fullwidth_to_ascii(text)
    text = _DASHES.sub("-", text)
    return text.replace("　", " ")


# ---------------------------------------------------------------------------
# 사업자등록번호
# ---------------------------------------------------------------------------
_BIZ = re.compile(r"(?<![\d-])(\d{3})\s?-\s?(\d{2})\s?-\s?(\d{5})(?![\d-])")
_BIZ_KEYWORD = re.compile(r"사업자\s*(?:등록)?\s*(?:번호)?\s*[:：]?\s*$")
_BIZ_WEIGHTS = (1, 3, 7, 1, 3, 7, 1, 3, 5)


def business_number_checksum_ok(digits: str) -> bool:
    """국세청 사업자등록번호 검증 숫자(마지막 자리) 계산."""
    if len(digits) != 10 or not digits.isdigit():
        return False
    d = [int(c) for c in digits]
    total = sum(x * w for x, w in zip(d[:9], _BIZ_WEIGHTS))
    total += (d[8] * 5) // 10
    return (10 - total % 10) % 10 == d[9]


@dataclass(frozen=True)
class BusinessNumber:
    digits: str  # 하이픈 없는 10자리
    checksum_ok: bool

    @property
    def formatted(self) -> str:
        return f"{self.digits[:3]}-{self.digits[3:5]}-{self.digits[5:]}"


# ---------------------------------------------------------------------------
# 마스킹 패턴 (적용 순서가 중요: 긴 번호 → 짧은 번호)
# ---------------------------------------------------------------------------
_SEP = r"[-.\s]?"
_RRN = re.compile(r"(?<![\d-])\d{6}\s?-\s?[1-8]\d{6}(?![\d-])")
_RRN_PLAIN = re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[1-8]\d{6}(?!\d)")
_CARD = re.compile(r"(?<![\d-])\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{3,4}(?![\d-])")
_PHONE_PATTERNS = [
    re.compile(r"\+\s?82[-.\s]?\(?0?\)?1[016789]" + _SEP + r"\d{3,4}" + _SEP + r"\d{4}(?!\d)"),
    re.compile(r"\+\s?(?!82)\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}(?!\d)"),
    re.compile(r"(?<![\d-])01[016789]" + _SEP + r"\d{3,4}" + _SEP + r"\d{4}(?![\d-])"),
    re.compile(r"(?<![\d-])\(?0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70|50[2-8])\)?" + _SEP + r"\d{3,4}" + _SEP + r"\d{4}(?![\d-])"),
    re.compile(r"(?<![\d-])1[5-9]\d{2}-\d{4}(?![\d-])"),  # 대표번호 1588-0000 등
]
_WA_ME = re.compile(r"(wa\.me/)(\+?\d{8,15})", re.IGNORECASE)
_BANKS = (
    "국민|KB|신한|우리|하나|농협|NH|기업|IBK|카카오뱅크|카뱅|토스뱅크|토스|케이뱅크|새마을금고|새마을|신협|"
    "우체국|수협|SC제일|제일|씨티|부산|대구|iM뱅크|경남|광주|전북|제주|산업|저축은행"
)
_ACCOUNT_CONTEXT = re.compile(
    r"((?:" + _BANKS + r")(?:은행)?|계좌(?:번호)?|입금\s*계좌|예금주\s*계좌)\s*[:：]?\s*(\d[\d\s-]{7,22}\d)"
)
_ACCOUNT_HYPHEN = re.compile(r"(?<![\d-])\d{2,6}(?:-\d{2,7}){2,3}(?![\d-])")
_LONG_DIGITS = re.compile(r"(?<![\d-])\d{10,16}(?![\d-])")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TME = re.compile(r"((?:https?://)?t\.me/)([A-Za-z0-9_]{4,32})", re.IGNORECASE)
_HANDLE = re.compile(r"(?<![\w@.])@([A-Za-z][A-Za-z0-9_.]{3,31})")
_MESSENGER_ID = re.compile(
    r"((?:카카오톡|카톡|카카오|텔레그램|텔레|텔그|라인|LINE|위챗|WeChat|인스타그램|인스타|아이디|ID|id)"
    r"\s*(?:아이디|ID|id)?\s*[:：]?\s*)"
    r"((?=[A-Za-z0-9_.\-]*[A-Za-z])[A-Za-z0-9_.\-]{4,32})(?![\w/:.])"  # 영문 포함 4자 이상, URL 조각 제외
)

# 사람 이름: 성씨 + 이름 1~3자, 앞뒤 문맥이 있을 때만 (오탐을 줄이기 위해)
_SURNAMES_2 = ("남궁", "황보", "제갈", "선우", "독고", "사공", "서문")
_SURNAMES_1 = set(
    "김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경봉사부"
)
_NAME_STOPWORDS = {
    "고객", "회원", "지원자", "구직자", "근로자", "여러분", "고용주", "사장", "기사", "학생", "직원", "알바생",
    "대표", "본인", "상담원", "관리자", "담당자", "매니저", "선생", "팀원", "신입", "경력", "점주", "손님",
    "기재", "확인", "작성", "제출", "업무", "문의", "연락", "모집", "번호", "승진", "면접", "직급", "수당",
    "회사", "정보", "미정", "공개", "고수익", "고액", "주말", "평일", "오전", "오후", "당일", "정산", "지급",
    "이체", "입금", "송금", "전달", "수거", "배송", "택배", "포장", "재택", "부업", "가능", "우대", "필수",
    "안내", "상담", "채용", "구인", "구함", "급구", "인원", "나이", "성별", "무관", "경험", "교육", "합숙",
    "지원", "신청", "참여", "진행", "시작", "종료", "근무", "출근", "퇴근", "시간", "월급", "일급", "시급",
    "주급", "연봉", "보너스", "인센티브", "수수료", "보증금", "장소", "지역", "서울", "부산", "대구", "인천",
    "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
    "해외", "국내", "공식", "본사", "지점", "매장", "센터", "주식회사", "유한회사", "명의", "계좌", "통장",
    "카드", "현금", "상품권", "코인", "문자", "친구", "지인", "소개", "추천", "이름", "성명", "예금주",
    "이사", "부장", "과장", "차장", "실장", "원장", "점장", "대리", "주임", "사원", "총무", "경리", "상무",
    "전무", "회장", "본부장", "센터장", "지점장", "고객센터", "이모", "삼촌", "언니", "오빠", "형님", "누나",
    "어머님", "아버님", "사모", "사모님", "부모님", "선배", "후배", "동생", "기간", "조건", "사항", "내용",
}
_TITLE = (
    r"(?:씨|님|대리님?|과장님?|차장님?|부장님?|팀장님?|실장님?|주임님?|매니저님?|사장님?|이사님?|"
    r"원장님?|점장님?|선생님|기사님|대표님)"
)
_NAME_AFTER_LABEL = re.compile(
    r"((?:담당자|담당|예금주|성명|이름|대표자|대표|채용\s?담당자?|인사\s?담당자?|"
    r"매니저|실장|팀장|과장|대리|부장|사장|원장|점장)\s*(?:은|는|:|：)?\s*)"
    r"([가-힣]{2,4}?)(?=입니다|이에요|예요|이고|님|씨|[\s,.)\]/]|$)"
)
_NAME_BEFORE_TITLE = re.compile(r"(?<![가-힣])([가-힣]{2,4})(\s?" + _TITLE + r")")
_NAME_SELF_INTRO = re.compile(
    r"((?<![가-힣])(?:저는|전|제\s?이름은|담당자는|[가-힣]{1,6}팀)\s*)([가-힣]{2,4})((?:입니다|이에요|예요|이고요|라고\s?합니다))"
)

TOKEN_LABELS = {
    "rrn": "주민번호",
    "card": "카드번호",
    "phone": "전화번호",
    "account": "계좌번호",
    "email": "이메일",
    "messenger_id": "메신저ID",
    "name": "이름",
}
TOKEN_PATTERN = re.compile(r"\[(?:" + "|".join(TOKEN_LABELS.values()) + r")\d+\]")


def _looks_like_name(candidate: str) -> bool:
    if candidate in _NAME_STOPWORDS:
        return False
    if any(candidate.startswith(s) for s in _SURNAMES_2):
        return 3 <= len(candidate) <= 4
    if candidate[0] not in _SURNAMES_1:
        return False
    if not 2 <= len(candidate) <= 4:
        return False
    # 앞 2글자가 흔한 단어이면 이름이 아님 (예: '고수익')
    return candidate[:2] not in _NAME_STOPWORDS and candidate[:3] not in _NAME_STOPWORDS


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


@dataclass
class MaskResult:
    masked_text: str
    counts: dict[str, int]  # 종류별 마스킹 개수 (화면 안내용)
    business_numbers: list[BusinessNumber]

    @property
    def total_masked(self) -> int:
        return sum(self.counts.values())


@dataclass
class Masker:
    """세션 하나에 하나. 같은 값은 같은 토큰으로 바꾼다(원래 값은 저장하지 않음)."""

    _salt: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    _seen: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def _token(self, kind: str, raw: str) -> str:
        key_src = _digits(raw) if kind in {"rrn", "card", "phone", "account"} else raw.strip().lower()
        digest = hashlib.blake2b(key_src.encode("utf-8"), key=self._salt, digest_size=12).hexdigest()
        key = f"{kind}:{digest}"
        if key not in self._seen:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            self._seen[key] = f"[{TOKEN_LABELS[kind]}{self._counters[kind]}]"
        return self._seen[key]

    def mask(self, text: str) -> MaskResult:
        text = preprocess(text)
        counts: dict[str, int] = {}

        def sub(kind: str, pattern: re.Pattern, s: str, group: int = 0, check=None) -> str:
            def repl(m: re.Match) -> str:
                target = m.group(group)
                if check is not None and not check(target, m):
                    return m.group(0)
                counts[kind] = counts.get(kind, 0) + 1
                token = self._token(kind, target)
                if group == 0:
                    return token
                start, end = m.start(group) - m.start(0), m.end(group) - m.start(0)
                whole = m.group(0)
                return whole[:start] + token + whole[end:]

            return pattern.sub(repl, s)

        # 1) 사업자번호를 먼저 찾아 보호(마스킹 대상 아님)
        business_numbers: list[BusinessNumber] = []
        protected: dict[str, str] = {}

        def protect_biz(m: re.Match) -> str:
            digits = "".join(m.groups())
            bn = BusinessNumber(digits, business_number_checksum_ok(digits))
            if bn not in business_numbers:
                business_numbers.append(bn)
            placeholder = f"\x00BIZ{len(protected)}\x00"
            protected[placeholder] = bn.formatted
            return placeholder

        text = _BIZ.sub(protect_biz, text)

        # 하이픈 없는 10자리 + 앞에 '사업자' 문맥 + 검증 숫자 일치 → 사업자번호
        def protect_plain_biz(m: re.Match) -> str:
            digits = m.group(0)
            prefix = text_ref[max(0, m.start() - 15): m.start()]
            if len(digits) == 10 and business_number_checksum_ok(digits) and _BIZ_KEYWORD.search(prefix):
                bn = BusinessNumber(digits, True)
                if bn not in business_numbers:
                    business_numbers.append(bn)
                placeholder = f"\x00BIZ{len(protected)}\x00"
                protected[placeholder] = bn.formatted
                return placeholder
            return digits

        text_ref = text
        text = _LONG_DIGITS.sub(protect_plain_biz, text)

        # 2) 번호류 (긴 것부터)
        text = sub("rrn", _RRN, text)
        text = sub("rrn", _RRN_PLAIN, text)
        text = sub("card", _CARD, text)
        text = sub("phone", _WA_ME, text, group=2)
        for p in _PHONE_PATTERNS:
            text = sub("phone", p, text)
        text = sub("account", _ACCOUNT_CONTEXT, text, group=2, check=lambda t, m: 8 <= len(_digits(t)) <= 16)
        text = sub("account", _ACCOUNT_HYPHEN, text, check=lambda t, m: 10 <= len(_digits(t)) <= 16)
        text = sub("account", _LONG_DIGITS, text)

        # 3) 이메일·메신저 ID
        text = sub("email", _EMAIL, text)
        text = sub("messenger_id", _TME, text, group=2)
        text = sub("messenger_id", _HANDLE, text, group=1)
        text = sub("messenger_id", _MESSENGER_ID, text, group=2)

        # 4) 사람 이름 (문맥이 있을 때만)
        is_name = lambda t, m: _looks_like_name(t)  # noqa: E731
        text = sub("name", _NAME_AFTER_LABEL, text, group=2, check=is_name)
        text = sub("name", _NAME_SELF_INTRO, text, group=2, check=is_name)
        text = sub("name", _NAME_BEFORE_TITLE, text, group=1, check=is_name)

        # 5) 사업자번호 복원
        for placeholder, value in protected.items():
            text = text.replace(placeholder, value)

        return MaskResult(masked_text=text, counts=counts, business_numbers=business_numbers)


def mask_text(text: str) -> MaskResult:
    """한 번만 쓰는 마스킹(세션 상태 불필요할 때)."""
    return Masker().mask(text)


# ---------------------------------------------------------------------------
# 인용 검증 (AI 가 인용한 문장이 마스킹된 원문에 실제로 있는지)
# ---------------------------------------------------------------------------
_ELLIPSIS = re.compile(r"\.{3,}|…|⋯|‥")


def normalize_for_match(text: str) -> str:
    """공백·문장부호·대소문자·전각 차이를 없앤 비교용 문자열."""
    text = unicodedata.normalize("NFKC", preprocess(text)).lower()
    return "".join(
        ch for ch in text if not ch.isspace() and not unicodedata.category(ch).startswith(("P", "S", "C"))
    )


def find_quote_spans(quote: str | None, text: str) -> list[tuple[int, int]]:
    """화면 하이라이트용: 인용문(말줄임표 조각별)이 원문에서 차지하는 위치. 공백·문장부호 차이는 허용."""
    if not quote:
        return []
    spans: list[tuple[int, int]] = []
    for part in _ELLIPSIS.split(quote):
        chars = [c for c in normalize_for_match(part)]
        if len(chars) < 2:
            continue
        gap = r"[\s\W_]*"
        pattern = gap.join(re.escape(c) for c in chars)
        m = re.search(pattern, text, re.IGNORECASE)  # 원문 위치를 그대로 쓰기 위해 원문에서 직접 찾는다
        if m:
            spans.append((m.start(), m.end()))
    return spans


def quote_in_text(quote: str | None, source_text: str, min_chars: int = 2) -> bool:
    """인용문이 원문에 있으면 True. 말줄임표(…)로 이어 붙인 인용은 조각마다 확인한다."""
    if not quote or not quote.strip():
        return False
    haystack = normalize_for_match(source_text)
    parts = [normalize_for_match(p) for p in _ELLIPSIS.split(quote)]
    parts = [p for p in parts if p]
    if not parts or sum(len(p) for p in parts) < min_chars:
        return False
    return all(p in haystack for p in parts)
