"""마스킹·인용 검증 단위 테스트 (가상 번호만 사용)."""
import pytest

from core.masking import Masker, business_number_checksum_ok, mask_text, quote_in_text


@pytest.mark.parametrize(
    "raw",
    [
        "010-1234-5678",
        "010 1234 5678",
        "01012345678",
        "010.1234.5678",
        "+82 10-1234-5678",
        "02-123-4567",
        "031-1234-5678",
        "0507-1234-5678",
        "070-1234-5678",
        "1588-1234",
        "０１０－１２３４－５６７８",  # 전각
    ],
)
def test_phone_numbers_are_masked(raw):
    r = mask_text(f"연락처 {raw} 로 문의")
    assert "[전화번호1]" in r.masked_text
    assert "1234" not in r.masked_text
    assert r.counts.get("phone") == 1


def test_rrn_card_account_email():
    text = (
        "주민번호 990101-1234567, 카드 1234-5678-9012-3456, "
        "신한 110-123-456789, 국민은행 123456-01-123456, 계좌번호: 3333 01 1234567, "
        "이메일 test.user@example.com"
    )
    r = mask_text(text)
    m = r.masked_text
    assert "[주민번호1]" in m
    assert "[카드번호1]" in m
    assert m.count("[계좌번호") == 3
    assert "[이메일1]" in m
    for leak in ("990101", "9012", "456789", "1234567", "example.com"):
        assert leak not in m


def test_messenger_ids():
    r = mask_text("텔레그램 @fastjob_kr 또는 t.me/fastjob_kr, 카톡 ID: hong1234 로 연락")
    m = r.masked_text
    assert "fastjob_kr" not in m and "hong1234" not in m
    assert m.count("[메신저ID1]") == 2  # 같은 ID → 같은 토큰
    assert "[메신저ID2]" in m
    assert "텔레그램" in m and "카톡" in m  # 채널 정보는 남긴다


@pytest.mark.parametrize(
    "text, name",
    [
        ("담당자 김민수 에게 연락", "김민수"),
        ("예금주: 홍길동", "홍길동"),
        ("이영희 과장이 안내합니다", "이영희"),
        ("저는 박지훈입니다", "박지훈"),
        ("인사팀 최수진입니다", "최수진"),
        ("남궁민수님 확인 부탁", "남궁민수"),
        ("대표 정하늘입니다", "정하늘"),
    ],
)
def test_names_with_context_are_masked(text, name):
    r = mask_text(text)
    assert name not in r.masked_text
    assert "[이름1]" in r.masked_text


@pytest.mark.parametrize(
    "text",
    [
        "고수익 보장, 고객님께 안내",
        "이사님 승인 후 진행",
        "시급 11,000원, 일당 15만 원, 월 1,000,000원",
        "근무일 2026-11-23, 09:00~18:00",
        "AI 데이터 라벨링 업무, 이미지를 분류하세요",
        "성명, 연락처를 기재해 주세요",
        "담당 업무는 포장입니다",
        "텔레그램 문의",
    ],
)
def test_ordinary_words_are_not_masked(text):
    r = mask_text(text)
    assert r.masked_text == text
    assert r.total_masked == 0


def test_business_number_is_kept_and_extracted():
    r = mask_text("사업자등록번호 000-00-00000 / 다른 번호 000-00-00001 / 연락 010-1234-5678")
    assert "000-00-00000" in r.masked_text  # 마스킹하지 않음
    assert [(b.formatted, b.checksum_ok) for b in r.business_numbers] == [
        ("000-00-00000", True),
        ("000-00-00001", False),
    ]
    assert "[전화번호1]" in r.masked_text


def test_plain_business_number_with_keyword():
    r = mask_text("사업자번호 0000000000 입니다")
    assert r.business_numbers and r.business_numbers[0].formatted == "000-00-00000"
    assert "[계좌번호" not in r.masked_text


def test_checksum():
    assert business_number_checksum_ok("0000000000")
    assert not business_number_checksum_ok("0000000001")
    assert not business_number_checksum_ok("12345")


def test_same_value_same_token_across_rounds():
    m = Masker()
    r1 = m.mask("연락 010-1234-5678")
    r2 = m.mask("다시 010 1234 5678 또는 010-9999-8888")
    assert "[전화번호1]" in r1.masked_text
    assert "[전화번호1]" in r2.masked_text
    assert "[전화번호2]" in r2.masked_text


def test_original_values_not_stored():
    m = Masker()
    m.mask("연락 010-1234-5678, 예금주: 홍길동")
    state = repr(m._seen) + repr(m._counters)
    assert "01012345678" not in state and "010-1234-5678" not in state and "홍길동" not in state


def test_quote_verification():
    src = mask_text("고액 알바! 고객님께 받은 현금을, 지정 장소에 전달하는 심부름. 텔레그램 @fastjob_kr").masked_text
    assert quote_in_text("고객님께 받은 현금을 지정 장소에 전달하는 심부름", src)  # 쉼표·공백 차이 허용
    assert quote_in_text("고액 알바 … 현금을 지정 장소에 전달", src)  # 말줄임표 조각 확인
    assert quote_in_text("텔레그램 [메신저ID1]", src)
    assert not quote_in_text("통장을 빌려주시면 됩니다", src)  # 원문에 없음
    assert not quote_in_text("", src)
    assert not quote_in_text(None, src)
