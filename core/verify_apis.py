"""공공 API 사실 확인: 국세청 사업자 상태 · 국민연금 가입 사업장 · 고용24(워크넷) 채용정보.

명세 확인(2026-11-23)
- 국세청 사업자등록 상태조회 (data.go.kr 15081808, Swagger infuser.odcloud.kr/api/stages/28493/api-docs):
  POST https://api.odcloud.kr/api/nts-businessman/v1/status?serviceKey=... , JSON {"b_no": ["10자리"]} (하이픈 없이,
  1회 최대 100건). 응답 data[].b_stt_cd 01 계속 / 02 휴업 / 03 폐업, 미등록이면 tax_type 에
  "국세청에 등록되지 않은 사업자등록번호입니다".
- 국민연금 가입 사업장 (data.go.kr 3046071, 페이지 내 Swagger): GET https://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2
  /getBassInfoSearchV2 (wkplNm 필수, bzowrRgstNo 앞 6자리·지역 코드 선택, dataType=json) → seq·사업장명·주소·등록상태.
  업종명(vldtVlKrnNm)·가입자수(jnngpCnt)는 /getDetailInfoSearchV2?seq=... 에 있다.
- 워크넷 채용정보 (data.go.kr 3038225 는 'LINK' 유형 → 고용24 OPEN-API 로 연결, 별도 인증키 authKey):
  GET https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do?authKey&callTp=L&returnType=XML
  &startPage=1&display=10[&busino|&keyword] → wantedRoot/wanted[company, busino, indTpNm, title, sal, region, wantedInfoUrl ...].
  공공누리 제4유형(출처표시·상업적 이용금지·변경금지) → 값을 바꾸지 않고 출처와 함께 보여 준다.

원칙
- 공식 공공 API 만 자동 호출한다. 민간 채용 사이트는 호출하지 않는다.
- 업체 정보(상호·사업자번호)만 보낸다. 공고 원문·개인정보는 보내지 않는다.
- 장애·키 없음은 해당 확인만 '조회 실패/조회 안 함'으로 두고 판정은 계속한다.
"""
from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote

from . import config
from .masking import BusinessNumber
from .rules_engine import RuleBook, load_rules
from .schema import (
    UNOFFICIAL_CONTACTS,
    Extraction,
    Facts,
    NpsCandidate,
    NpsResult,
    NtsResult,
    WorknetPosting,
    WorknetResult,
)

KST = timezone(timedelta(hours=9))
NTS_URL = "https://api.odcloud.kr/api/nts-businessman/v1/status"
NPS_BASE = "https://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2"
WORK24_URL = "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do"
WORK24_SOURCE = "출처: 고용24(한국고용정보원) 채용정보 OPEN-API · 공공누리 제4유형(출처표시·상업적 이용금지·변경금지) · 내용을 바꾸지 않고 표시"
WORKNET_DISABLED_NOTE = ("이번 버전에서는 제외했습니다(고용24 OPEN-API 는 기업회원 전용·심사 후 인증키 발급). "
                         "코드는 준비돼 있어 인증키를 받으면 켤 수 있는 확장 기능입니다.")
TIMEOUT_S = 15  # 국민연금 API 는 실측 응답 5~10초(2026-11-23)
CACHE_TTL_S = 3600  # 같은 업체 재조회 방지(공공 API 트래픽·응답 시간 절약)
NTS_NOT_REGISTERED = "등록되지 않은"
_CORP_WORDS = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(재\)|재단법인|\(사\)|사단법인|\s+")


def _now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


def _key(name: str) -> str | None:
    """data.go.kr 은 Encoding/Decoding 키를 둘 다 준다. requests 가 다시 인코딩하므로 디코딩한 값으로 통일."""
    raw = config.get_secret(name)
    if not raw:
        return None
    raw = raw.strip()
    return unquote(raw) if "%" in raw else raw


def normalize_company(name: str | None) -> str:
    return _CORP_WORDS.sub("", name or "").lower()


def _tokens(text: str | None) -> set[str]:
    return {t for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", text or "")}


def _region_tokens(text: str | None) -> set[str]:
    """'서울 마포구 망원동' → {'서울', '마포', '망원'} 처럼 시·구·동 어간."""
    out = set()
    for t in _tokens(text):
        out.add(re.sub(r"(특별시|광역시|특별자치시|특별자치도|시|군|구|동|읍|면|도)$", "", t) or t)
    return {t for t in out if len(t) >= 2}


# ---------------------------------------------------------------------------
# 국세청
# ---------------------------------------------------------------------------
def check_nts(session, key: str | None, bn: BusinessNumber | None) -> NtsResult:
    if bn is None:
        return NtsResult(status="not_checked", message="공고에 사업자등록번호가 없어 조회하지 않았습니다.")
    if not key:
        return NtsResult(status="not_checked", business_number=bn.formatted, message="공공데이터 인증키가 설정되지 않았습니다.")
    try:
        resp = session.post(NTS_URL, params={"serviceKey": key}, json={"b_no": [bn.digits]}, timeout=TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        item = (data.get("data") or [{}])[0]
    except Exception as exc:  # 네트워크·형식 오류 → 판정은 계속
        return NtsResult(status="error", business_number=bn.formatted, checked_at=_now(),
                         message=f"국세청 조회 실패({type(exc).__name__})")
    code = str(item.get("b_stt_cd") or "")
    status = {"01": "active", "02": "suspended", "03": "closed"}.get(code)
    if status is None and NTS_NOT_REGISTERED in str(item.get("tax_type") or ""):
        status = "not_registered"
    if status is None:
        return NtsResult(status="error", business_number=bn.formatted, checked_at=_now(), message="국세청 응답을 해석하지 못했습니다.")
    msg = item.get("b_stt") or item.get("tax_type")
    if status == "closed" and item.get("end_dt"):
        msg = f"{msg} (폐업일 {item['end_dt']})"
    return NtsResult(status=status, business_number=bn.formatted, checked_at=_now(), message=msg)


# ---------------------------------------------------------------------------
# 국민연금
# ---------------------------------------------------------------------------
def _nps_items(payload: dict) -> tuple[list[dict], int]:
    root = payload.get("response", payload)
    header = root.get("header") or {}
    if str(header.get("resultCode", "00")) not in {"00", "0", "000"}:
        raise RuntimeError(f"resultCode={header.get('resultCode')}")
    body = root.get("body") or {}
    items = body.get("items") or {}
    item = items.get("item") if isinstance(items, dict) else items
    if item is None or item == "":
        item = []
    if isinstance(item, dict):
        item = [item]
    return list(item), int(body.get("totalCount") or len(item))


def check_nps(session, key: str | None, company: str | None, region: str | None, bn: BusinessNumber | None) -> NpsResult:
    if not company:
        return NpsResult(match="not_checked", message="공고에 업체명이 없어 조회하지 않았습니다.")
    if not key:
        return NpsResult(match="not_checked", message="공공데이터 인증키가 설정되지 않았습니다.")
    params: dict[str, Any] = {"serviceKey": key, "wkplNm": company.strip(), "pageNo": 1, "numOfRows": 20, "dataType": "json"}
    if bn is not None:
        params["bzowrRgstNo"] = bn.digits[:6]
    try:
        resp = session.get(f"{NPS_BASE}/getBassInfoSearchV2", params=params, timeout=TIMEOUT_S)
        resp.raise_for_status()
        items, _total = _nps_items(resp.json())
    except Exception as exc:
        return NpsResult(match="error", checked_at=_now(), message=f"국민연금 조회 실패({type(exc).__name__})")

    target = normalize_company(company)
    # 같은 사업장이 자료생성년월(dataCrtYm)마다 따로 나오므로(실측) 이름·주소·사업자번호 앞자리가 같으면 최신 한 건만 남긴다
    latest: dict[tuple, dict] = {}
    for it in items:
        k = (normalize_company(str(it.get("wkplNm") or "")), str(it.get("wkplRoadNmDtlAddr") or ""),
             str(it.get("bzowrRgstNo") or ""))
        if k not in latest or str(it.get("dataCrtYm") or "") > str(latest[k].get("dataCrtYm") or ""):
            latest[k] = it
    cands = [
        NpsCandidate(
            name=str(it.get("wkplNm") or ""),
            seq=str(it.get("seq") or "") or None,
            biz_prefix6=str(it.get("bzowrRgstNo") or "") or None,
            address=str(it.get("wkplRoadNmDtlAddr") or "") or None,
            status={"1": "등록", "2": "탈퇴"}.get(str(it.get("wkplJnngStcd")), None),
        )
        for it in latest.values()
    ]
    # 이름이 같거나 한쪽이 다른 쪽을 포함하는 사업장만 후보로 본다(부분 일치 검색 대비)
    cands = [c for c in cands if target and (target in normalize_company(c.name) or normalize_company(c.name) in target)]
    # 이름이 정확히 같은 사업장이 있으면 그것만(예: '…/일용/○○공사' 같은 현장 사업장 제외), 등록 중인 곳이 있으면 탈퇴 제외
    exact = [c for c in cands if normalize_company(c.name) == target]
    cands = exact or cands
    active = [c for c in cands if c.status != "탈퇴"]
    cands = active or cands
    reg = _region_tokens(region)
    if reg and len(cands) > 1:
        narrowed = [c for c in cands if reg & _region_tokens(c.address)]
        cands = narrowed or cands
    if not cands:
        return NpsResult(match="none", checked_at=_now(),
                         message="국민연금 가입 사업장에서 찾지 못했습니다(3인 이상 법인 등 일부만 공개, 위험 신호 아님).")
    if len(cands) > 1:
        return NpsResult(match="multiple", candidates=cands[:10], checked_at=_now(), message=f"같은 이름 후보 {len(cands)}곳")

    c = cands[0]
    if c.seq:  # 업종·가입자수는 상세 조회에 있다
        try:
            r2 = session.get(f"{NPS_BASE}/getDetailInfoSearchV2",
                             params={"serviceKey": key, "seq": c.seq, "pageNo": 1, "numOfRows": 1, "dataType": "json"},
                             timeout=TIMEOUT_S)
            r2.raise_for_status()
            detail, _ = _nps_items(r2.json())
            if detail:
                d = detail[0]
                c.industry = str(d.get("vldtVlKrnNm") or "") or None
                try:
                    c.members = int(str(d.get("jnngpCnt") or "").strip() or 0) or None
                except ValueError:
                    c.members = None
                c.registered_at = str(d.get("adptDt") or "") or None
        except Exception:
            pass  # 기본 정보만으로도 '1곳 확인'은 유지
    return NpsResult(match="single", candidates=[c], checked_at=_now(), message="1곳 확인")


# ---------------------------------------------------------------------------
# 고용24(워크넷) 채용정보
# ---------------------------------------------------------------------------
def _xml_text(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def parse_work24(xml_text: str) -> tuple[int, list[dict]]:
    root = ET.fromstring(xml_text)
    if root.tag != "wantedRoot":
        msg = _xml_text(root, "message") or root.tag
        raise RuntimeError(f"고용24 응답 오류: {msg}")
    total = int(_xml_text(root, "total") or 0)
    rows = []
    for w in root.findall("wanted"):
        rows.append({t: _xml_text(w, t) for t in (
            "company", "busino", "indTpNm", "title", "sal", "salTpNm", "region", "regDt", "closeDt", "wantedInfoUrl", "basicAddr")})
    return total, rows


def check_worknet(session, key: str | None, ex: Extraction, bn: BusinessNumber | None) -> WorknetResult:
    if not key:
        return WorknetResult(match="disabled", detail=WORKNET_DISABLED_NOTE)
    company = ex.company.name
    if bn is None and not company:
        return WorknetResult(match="not_checked", detail="업체명·사업자등록번호가 없어 조회하지 않았습니다.")
    params: dict[str, Any] = {"authKey": key, "callTp": "L", "returnType": "XML", "startPage": 1, "display": 20}
    if bn is not None:
        params["busino"] = bn.digits
    else:
        params["keyword"] = company
    try:
        resp = session.get(WORK24_URL, params=params, timeout=TIMEOUT_S)
        resp.raise_for_status()
        total, rows = parse_work24(resp.text)
    except Exception as exc:
        return WorknetResult(match="error", checked_at=_now(), detail=f"고용24 조회 실패({type(exc).__name__})")

    if bn is None:  # 키워드 검색은 제목에도 걸리므로 회사명이 같은 공고만 남긴다
        target = normalize_company(company)
        rows = [r for r in rows if target and target == normalize_company(r.get("company"))]
    postings = [WorknetPosting(company=r["company"], title=r["title"], region=r["region"], industry=r["indTpNm"],
                               sal=r["sal"], reg_dt=r["regDt"], close_dt=r["closeDt"], url=r["wantedInfoUrl"]) for r in rows]
    if not postings:
        return WorknetResult(match="none", checked_at=_now(), total=0,
                             detail="같은 업체의 공식 공고를 찾지 못했습니다(공고를 올리지 않은 업체일 수 있음).")

    # 공식 공고 일치 = 같은 업체 + 근무 지역 일치 + 직무 단어 겹침. 연락처는 API 에 없어 대조하지 못한다.
    reg = _region_tokens(" ".join(filter(None, [ex.company.region, ex.job.work_location])))
    job_words = _tokens(" ".join(filter(None, [ex.job.title, ex.job.duties_summary])))
    best = None
    for p in postings:
        region_ok = bool(reg) and bool(reg & _region_tokens(p.region))
        title_ok = bool(job_words & _tokens(p.title))
        if region_ok and title_ok:
            best = p
            break
    unofficial = bool(set(ex.contact.channels) & UNOFFICIAL_CONTACTS)
    if best is not None and not unofficial:
        return WorknetResult(match="match", checked_at=_now(), total=len(postings), postings=postings[:5], url=best.url,
                             detail=f"공식 공고와 업체·지역·직무가 일치합니다: {best.title} ({best.region})")
    if reg and not any(reg & _region_tokens(p.region) for p in postings):
        return WorknetResult(match="mismatch", checked_at=_now(), total=len(postings), postings=postings[:5],
                             detail="같은 업체의 공식 공고는 있지만 근무 지역이 다릅니다.")
    note = ("같은 업체의 공식 공고는 있지만, 받은 공고는 개인 메신저·문자로 연락합니다. 공식 공고의 연락처로 직접 확인하세요."
            if unofficial else "같은 업체의 공식 공고가 있지만 이 공고와 같은 공고인지 확인되지 않았습니다.")
    return WorknetResult(match="none", checked_at=_now(), total=len(postings), postings=postings[:5], detail=note)


# ---------------------------------------------------------------------------
# M4 업종 불일치 (보수적)
# ---------------------------------------------------------------------------
def industry_mismatch(ex: Extraction, industries: list[str], rb: RuleBook) -> tuple[bool | None, str | None]:
    cfg = rb.industry_mismatch or {}
    risk = cfg.get("risk_industry_keywords") or []
    related = cfg.get("related_job_keywords") or []
    known = [i for i in industries if i]
    if not known:
        return None, None
    job_text = " ".join(filter(None, [ex.job.title, ex.job.duties_summary]))
    for ind in known:
        hit = next((k for k in risk if k in ind), None)
        if hit and not any(k in job_text for k in related):
            return True, f"등록 업종 '{ind}'와 공고 직무 '{ex.job.title or ex.job.duties_summary or '미기재'}'가 다릅니다."
    return False, None


# ---------------------------------------------------------------------------
# 묶음
# ---------------------------------------------------------------------------
class _TTLCache:
    """프로세스 공용 캐시(같은 업체 재조회 방지). 실패 결과는 저장하지 않는다."""

    def __init__(self, ttl: float):
        self.ttl, self._d, self._lock = ttl, {}, threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._d.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1].model_copy(deep=True)
            return None

    def put(self, key, value):
        if getattr(value, "status", None) == "error" or getattr(value, "match", None) == "error":
            return
        with self._lock:
            self._d[key] = (time.time(), value.model_copy(deep=True))


_CACHE = _TTLCache(CACHE_TTL_S)


def clear_cache() -> None:
    with _CACHE._lock:
        _CACHE._d.clear()


def _cached(key, fn):
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    value = fn()
    _CACHE.put(key, value)
    return value


class PublicDataChecker:
    """pipeline.FactChecker 구현. 세 조회를 동시에 돌리고, 같은 업체는 2회차·다른 세션에서 다시 조회하지 않는다."""

    def __init__(self, session=None, data_key: str | None = None, work24_key: str | None = None,
                 rulebook: RuleBook | None = None):
        if session is None:
            import requests

            session = requests.Session()
            session.headers["User-Agent"] = "gonggo-dotbogi/1.0"
        self.session = session
        self.data_key = data_key if data_key is not None else _key("DATA_GO_KR_SERVICE_KEY")
        self.work24_key = work24_key if work24_key is not None else _key("WORK24_AUTH_KEY")
        self.rulebook = rulebook or load_rules()

    def __call__(self, ex: Extraction, business_numbers: list[BusinessNumber], prior: Facts | None) -> Facts:
        bn = next((b for b in business_numbers if b.checksum_ok), None)
        same_target = prior is not None and getattr(self, "_last_target", None) == (ex.company.name, bn)
        if same_target:
            facts = prior.model_copy(deep=True)
        else:
            region = " ".join(filter(None, [ex.company.region, ex.job.work_location]))
            with ThreadPoolExecutor(max_workers=3) as pool:
                f_nts = pool.submit(_cached, ("nts", bn), lambda: check_nts(self.session, self.data_key, bn))
                f_nps = pool.submit(_cached, ("nps", normalize_company(ex.company.name), region, bn),
                                    lambda: check_nps(self.session, self.data_key, ex.company.name, region, bn))
                f_wn = pool.submit(check_worknet, self.session, self.work24_key, ex, bn)
                facts = Facts(nts=f_nts.result(), nps=f_nps.result(), worknet=f_wn.result())
        self._last_target = (ex.company.name, bn)
        industries = [c.industry for c in facts.nps.candidates if facts.nps.match == "single" and c.industry]
        industries += [p.industry for p in facts.worknet.postings if p.industry]
        facts.industry_mismatch, facts.industry_mismatch_detail = industry_mismatch(ex, industries, self.rulebook)
        return facts
