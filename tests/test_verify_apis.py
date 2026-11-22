"""공공 API 사실 확인 테스트. 실제 API 는 부르지 않고, 명세의 응답 형식을 흉내 낸 가짜 세션을 쓴다."""
from conftest import make_extraction, sig
from core.masking import BusinessNumber, Masker, mask_text
from core.pipeline import analyze
from core.rules_engine import judge, load_rules
from core.verify_apis import (
    NPS_BASE,
    NTS_URL,
    WORK24_URL,
    PublicDataChecker,
    _key,
    check_nps,
    check_nts,
    check_worknet,
    industry_mismatch,
    parse_work24,
)

RB = load_rules()
BN = BusinessNumber("0000000000", True)


class FakeResp:
    def __init__(self, json_data=None, text="", status=200):
        self._json, self.text, self.status_code = json_data, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _hit(self, method, url, **kw):
        self.calls.append((method, url, kw))
        r = self.routes.get(url)
        if isinstance(r, Exception):
            raise r
        return r(kw) if callable(r) else r

    def post(self, url, **kw):
        return self._hit("POST", url, **kw)

    def get(self, url, **kw):
        return self._hit("GET", url, **kw)


def nts_resp(code=None, tax_type="부가가치세 일반과세자", end_dt=""):
    item = {"b_no": "0000000000", "b_stt": {"01": "계속사업자", "02": "휴업자", "03": "폐업자"}.get(code, ""),
            "b_stt_cd": code or "", "tax_type": tax_type, "end_dt": end_dt}
    return FakeResp({"status_code": "OK", "request_cnt": 1, "match_cnt": 1, "data": [item]})


# ---------------------------------------------------------------------------
# 국세청
# ---------------------------------------------------------------------------
def test_nts_status_codes():
    for code, expected in (("01", "active"), ("02", "suspended"), ("03", "closed")):
        s = FakeSession({NTS_URL: nts_resp(code, end_dt="20260101" if code == "03" else "")})
        r = check_nts(s, "KEY", BN)
        assert r.status == expected
    call = s.calls[0]
    assert call[0] == "POST" and call[2]["json"] == {"b_no": ["0000000000"]} and call[2]["params"]["serviceKey"] == "KEY"
    assert "폐업일 20260101" in r.message


def test_nts_not_registered_and_failures():
    s = FakeSession({NTS_URL: nts_resp(None, tax_type="국세청에 등록되지 않은 사업자등록번호입니다.")})
    assert check_nts(s, "KEY", BN).status == "not_registered"
    assert check_nts(FakeSession({NTS_URL: TimeoutError()}), "KEY", BN).status == "error"
    assert check_nts(FakeSession({NTS_URL: FakeResp({}, status=500)}), "KEY", BN).status == "error"
    assert check_nts(FakeSession({}), None, BN).status == "not_checked"
    assert check_nts(FakeSession({}), "KEY", None).status == "not_checked"


# ---------------------------------------------------------------------------
# 국민연금
# ---------------------------------------------------------------------------
def nps_search(items, wrap=True):
    body = {"pageNo": 1, "numOfRows": 20, "totalCount": len(items), "items": {"item": items if len(items) != 1 else items[0]}}
    payload = {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": body}
    return FakeResp({"response": payload} if wrap else payload)


def nps_item(name, addr, seq="1", stcd="1"):
    return {"wkplNm": name, "wkplRoadNmDtlAddr": addr, "seq": seq, "bzowrRgstNo": "000000", "wkplJnngStcd": stcd}


def test_nps_single_with_detail():
    detail = FakeResp({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [
        {"vldtVlKrnNm": "제과점업", "jnngpCnt": "12", "adptDt": "20200101"}]}}}})
    s = FakeSession({f"{NPS_BASE}/getBassInfoSearchV2": nps_search([nps_item("(주)가상제빵", "서울특별시 마포구 망원로 1")]),
                     f"{NPS_BASE}/getDetailInfoSearchV2": detail})
    r = check_nps(s, "KEY", "가상제빵", "망원", BN)
    assert r.match == "single"
    c = r.candidates[0]
    assert c.industry == "제과점업" and c.members == 12 and c.status == "등록"
    params = s.calls[0][2]["params"]
    assert params["wkplNm"] == "가상제빵" and params["bzowrRgstNo"] == "000000" and params["dataType"] == "json"


def test_nps_multiple_none_and_region_narrowing():
    two = [nps_item("가상물류", "서울특별시 송파구 1", "1"), nps_item("가상물류", "부산광역시 해운대구 2", "2")]
    s = FakeSession({f"{NPS_BASE}/getBassInfoSearchV2": nps_search(two, wrap=False)})
    assert check_nps(s, "KEY", "가상물류", None, None).match == "multiple"
    s2 = FakeSession({f"{NPS_BASE}/getBassInfoSearchV2": nps_search(two),
                      f"{NPS_BASE}/getDetailInfoSearchV2": FakeResp({"response": {"header": {"resultCode": "00"}, "body": {"items": ""}}})})
    assert check_nps(s2, "KEY", "가상물류", "부산 해운대", None).match == "single"
    s3 = FakeSession({f"{NPS_BASE}/getBassInfoSearchV2": nps_search([nps_item("전혀다른회사", "서울")])})
    r3 = check_nps(s3, "KEY", "가상물류", None, None)
    assert r3.match == "none" and "위험 신호 아님" in r3.message


def test_nps_error_and_skip():
    bad = FakeResp({"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED"}}})
    assert check_nps(FakeSession({f"{NPS_BASE}/getBassInfoSearchV2": bad}), "KEY", "가상", None, None).match == "error"
    assert check_nps(FakeSession({}), "KEY", None, None, None).match == "not_checked"
    assert check_nps(FakeSession({}), None, "가상", None, None).match == "not_checked"


# ---------------------------------------------------------------------------
# 고용24(워크넷)
# ---------------------------------------------------------------------------
def work24_xml(rows, total=None):
    wanted = "".join(
        "<wanted>" + "".join(f"<{k}>{v}</{k}>" for k, v in r.items()) + "</wanted>" for r in rows)
    return FakeResp(text=f"<?xml version='1.0' encoding='UTF-8'?><wantedRoot><total>{total if total is not None else len(rows)}</total>"
                         f"<startPage>1</startPage><display>20</display>{wanted}</wantedRoot>")


POSTING = {"company": "가상제빵", "busino": "0000000000", "indTpNm": "제과점업", "title": "주말 매장 스태프 모집",
           "sal": "시급 11000원", "region": "서울 마포구", "regDt": "26-11-20", "closeDt": "26-12-20",
           "wantedInfoUrl": "https://www.work24.go.kr/example"}


def _ex(channels, region="마포 망원", title="주말 매장 스태프"):
    ex = make_extraction(company_name="가상제빵", channels=channels)
    return ex.model_copy(update={"company": ex.company.model_copy(update={"region": region}),
                                 "job": ex.job.model_copy(update={"title": title})})


def test_parse_work24_and_error():
    total, rows = parse_work24(work24_xml([POSTING]).text)
    assert total == 1 and rows[0]["company"] == "가상제빵" and rows[0]["indTpNm"] == "제과점업"
    try:
        parse_work24("<error><message>인증키 오류</message></error>")
        raise AssertionError("should fail")
    except RuntimeError as e:
        assert "인증키 오류" in str(e)


def test_worknet_match_requires_region_title_and_official_contact():
    s = FakeSession({WORK24_URL: work24_xml([POSTING])})
    r = check_worknet(s, "W24", _ex(["platform_message"]), BN)
    assert r.match == "match" and r.postings[0].url == "https://www.work24.go.kr/example"
    assert s.calls[0][2]["params"]["busino"] == "0000000000" and s.calls[0][2]["params"]["authKey"] == "W24"
    # 같은 업체 공고가 있어도 개인 메신저로 연락하면 '일치'로 보지 않는다
    r2 = check_worknet(FakeSession({WORK24_URL: work24_xml([POSTING])}), "W24", _ex(["telegram"]), BN)
    assert r2.match == "none" and "개인 메신저" in r2.detail
    # 지역이 다르면 불일치
    r3 = check_worknet(FakeSession({WORK24_URL: work24_xml([POSTING])}), "W24", _ex(["platform_message"], region="부산 해운대"), BN)
    assert r3.match == "mismatch"


def test_worknet_keyword_search_filters_company_and_handles_failures():
    other = dict(POSTING, company="다른회사")
    s = FakeSession({WORK24_URL: work24_xml([other])})
    r = check_worknet(s, "W24", _ex(["platform_message"]), None)
    assert s.calls[0][2]["params"]["keyword"] == "가상제빵" and r.match == "none"
    assert check_worknet(FakeSession({}), None, _ex([]), BN).match == "disabled"
    assert check_worknet(FakeSession({WORK24_URL: ConnectionError()}), "W24", _ex([]), BN).match == "error"


# ---------------------------------------------------------------------------
# M4·묶음·파이프라인
# ---------------------------------------------------------------------------
def test_industry_mismatch_is_conservative():
    office = make_extraction()
    office = office.model_copy(update={"job": office.job.model_copy(update={"title": "사무 보조"})})
    assert industry_mismatch(office, ["다단계판매업"], RB)[0] is True
    sales = office.model_copy(update={"job": office.job.model_copy(update={"title": "방문 판매원"})})
    assert industry_mismatch(sales, ["방문판매업"], RB)[0] is False
    assert industry_mismatch(office, ["제과점업"], RB)[0] is False
    assert industry_mismatch(office, [], RB)[0] is None


def test_checker_end_to_end_and_m4_in_verdict():
    from core.verify_apis import clear_cache

    clear_cache()
    detail = FakeResp({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": {"vldtVlKrnNm": "후원방문판매업"}}}}})
    s = FakeSession({
        NTS_URL: nts_resp("01"),
        f"{NPS_BASE}/getBassInfoSearchV2": nps_search([nps_item("가상에듀", "서울 강남구")]),
        f"{NPS_BASE}/getDetailInfoSearchV2": detail,
        WORK24_URL: work24_xml([]),
    })
    checker = PublicDataChecker(session=s, data_key="KEY", work24_key="W24", rulebook=RB)
    text = "[채용 플랫폼] 가상에듀 사무직 신입, 사업자등록번호 000-00-00000, 시급 11,000원"
    ex = make_extraction(company_name="가상에듀")
    ex = ex.model_copy(update={"job": ex.job.model_copy(update={"title": "사무직 신입"})})
    m = mask_text(text)
    facts = checker(ex, m.business_numbers, None)
    assert facts.nts.status == "active" and facts.nps.match == "single" and facts.industry_mismatch is True
    v = judge(ex, m.masked_text, "platform", facts=facts, business_numbers=m.business_numbers)
    assert v.grade == "yellow" and "M4" in v.matched_ids


def test_pipeline_does_not_query_hallucinated_company_name():
    seen = {}

    def checker(ex, biz, prior):
        seen["name"] = ex.company.name
        from core.schema import Facts
        return Facts()

    class Ex:
        name = "fake"

        def __call__(self, masked_text, source_channel, round_no):
            return make_extraction(company_name="원문에없는상호", signals=[sig("S3", "재택 부업")])

    analyze("재택 부업 관심 있으시면 연락 주세요", "sns_messenger", Masker(), Ex(), fact_checker=checker)
    assert seen["name"] is None


def test_service_key_encoding_is_normalized(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "abc%2Bdef%3D%3D")
    assert _key("DATA_GO_KR_SERVICE_KEY") == "abc+def=="
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "abc+def==")
    assert _key("DATA_GO_KR_SERVICE_KEY") == "abc+def=="


def test_nps_dedupes_monthly_rows_and_prefers_exact_active_name():
    rows = [
        dict(nps_item("가상물류주식회사", "서울 송파구 1", "1"), dataCrtYm="202509"),
        dict(nps_item("가상물류주식회사", "서울 송파구 1", "2"), dataCrtYm="202510"),
        nps_item("가상물류주식회사/일용/○○현장", "경기 오산시 2", "3", stcd="2"),
    ]
    detail = FakeResp({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [{"vldtVlKrnNm": "일반 창고업"}]}}}})
    s = FakeSession({f"{NPS_BASE}/getBassInfoSearchV2": nps_search(rows), f"{NPS_BASE}/getDetailInfoSearchV2": detail})
    r = check_nps(s, "KEY", "가상물류(주)", None, None)
    assert r.match == "single" and r.candidates[0].seq == "2" and r.candidates[0].industry == "일반 창고업"


def test_worknet_disabled_note_says_extension():
    r = check_worknet(FakeSession({}), None, _ex([]), BN)
    assert r.match == "disabled" and "확장" in r.detail
