# 공고돋보기

**지원 전, 구인 공고와 DM의 위험 신호를 판독합니다.**
CrAI LAB · 2026 대한민국 청년 CAREER FAIR AI 해커톤 출품작

> **고지** · 이 서비스의 판정은 AI가 생성한 결과를 포함하며 참고용입니다 · 법률 자문이 아닙니다 · 공공데이터를 활용한 개인 프로젝트이며 어떤 기관의 인증·제휴도 아닙니다 · 저장소의 시연·테스트 데이터는 가상으로 만들었거나 정부 자료에 실린 사기 공고 예시 문구입니다. 실제 개인정보는 없습니다.

## 무엇을 하나요
SNS·메신저로 받은 구인 공고나 DM을 붙여넣으면 다음 순서로 확인합니다.

1. **AI 판독** — OpenAI 모델이 공고에서 위험 신호 후보를 찾고 근거가 된 원문 문장을 인용합니다. 인용문이 원문에 실제로 있는지 코드가 다시 확인합니다. 없으면 그 신호를 낮춥니다.
2. **사실 확인** — 공공데이터 API로 사업자 상태(국세청)와 실재 사업장·업종(국민연금)을 조회합니다.
3. **판정** — 정부 공식 자료에 근거한 규칙(`rules/rules.yaml`)이 5단계 등급을 정합니다. **AI는 등급을 정하지 않습니다.**
4. **안내** — 근거 카드, 법적 결과, 신고처, 구인자에게 보낼 확인 질문을 보여 줍니다.
5. **2회차** — 구인자에게 받은 답변을 붙여넣으면 앞의 내용과 합쳐 다시 판정합니다.

## 바로 써 보기
- 배포 주소: https://gonggo-dotbogi.streamlit.app/ — 로그인 없이 실행됩니다.
- 화면의 **샘플 불러오기**로 가상 공고 5종을 바로 판독해 볼 수 있습니다.
- Streamlit Community Cloud 앱은 12시간 동안 방문이 없으면 잠듭니다. 잠든 화면이 나오면 **'Yes, get this app back up!'** 버튼을 누르고 잠시 기다려 주세요(누구나 깨울 수 있습니다).
- 비용 보호를 위해 세션당·하루 호출 상한이 있습니다(기본 세션당 15회, 하루 150회). 상한을 넘으면 미리 판독해 둔 샘플 결과를 안내합니다.

## 판정 등급
| 등급 | 뜻 |
|---|---|
| 🔴 위험 신호 발견 | 결정적 신호가 하나라도 있거나 원칙 A~D 위반 |
| 🟠 사칭 의심 | 유명 브랜드·'공식'을 내세우면서 문자·개인 메신저·외부 링크로 연락 |
| 🟡 주의 | 중간 신호, 약한 신호 2개 이상(신뢰 신호가 있으면 3개 이상), 또는 원칙 E·F 위반(신뢰 신호가 없을 때) |
| ⚪ 확인 필요 | 정보가 부족해 판단하기 어려움 → 확인 질문 |
| 🟢 낮은 위험(확인 권장) | 신뢰 신호가 있고 결정적·중간 신호가 없으며 약한 신호가 기준보다 적음. 업체명을 확인할 수 없으면(M2) ⚪로 둡니다. 이 경우에도 직접 확인을 권합니다 |

## 판정 규칙 요약
전체 문구·근거·확인 질문은 [`rules/rules.yaml`](rules/rules.yaml)에 있습니다.

| 묶음 | 규칙 |
|---|---|
| 결정적 신호(🔴) | H1 자금 경유 · H2 현금·물품 수거·전달·보관·운반 · H3 지원자 돈 투입 · H4 채용 확정 전 신분증 사본·계좌번호 요구 · H5 명의·계정 대여, 휴대폰·유심 개통 · H6 대량 문자 발송·지인 모집 보상 · H7 해외 근무 + 항공권·숙식·무비자·과도한 고수익 · H8 폐업 사업자 |
| 중간 신호(🟡 이상) | M1 외부 사이트·앱 가입 유도 · M3 직무 위장 의심 · M4 업종 불일치 · M5 성별·연령 한정 + 과도한 급여 |
| 사칭(🟠) | I1 사칭 의심 — 이번 버전은 '유명 브랜드·공식 표방(원문 인용 확인) + 비공식 연락 경로'로 판정합니다 |
| 약한 신호(2개 이상 → 🟡, 신뢰 신호가 있으면 3개 이상) | S1 고수익·당일 지급 강조 · S2 외부 메신저·오픈채팅 이동 유도 · S3 업무 내용 모호 · S4 최저임금 대비 과도한 급여 · M2 정식 플랫폼 공고인데 업체명 없음(v2.1.4부터 약한 신호, 🟢를 막음) |
| 신뢰 신호 | T2 정식 채용 플랫폼 출처 (T1 공식 공고 일치는 확장 예정) |
| 원칙 6축(처음 보는 수법 대응) | A 근로자 자산 선유출 · B 제3자 가치 통로 · C 불법·제3자 피해 · D 통제 상실 · E 검증 회피 · F 보상 비정상 |
| 그 밖의 표시 | X1 판정기를 조종하려는 문장 · L1 근로조건 위법 가능(최저임금 미달) |

규칙은 대회 제출본 기간 동안 고정합니다. 새 규칙은 사람이 공식 근거를 확인·승인한 뒤에만 추가하도록 설계했습니다.

## 규칙의 근거가 된 수법 10종
정부 자료 12건(2013~2026)으로 확인한 수법입니다.

| 수법 | 근거 자료 |
|---|---|
| 구매대행·리뷰·팀미션 | [정책브리핑 2024-06-10](https://www.korea.kr/news/policyNewsView.do?newsId=148930068) · [정책브리핑 카드뉴스 2026-08-12](https://www.korea.kr/multi/visualNewsView.do?newsId=148969916) |
| 유명 브랜드 사칭 리뷰 체험단 | [정책브리핑 카드뉴스 2024-04-23](https://www.korea.kr/multi/visualNewsView.do?newsId=148928265) |
| 개인정보 탈취·계정 대여 | [정책브리핑 2025-11-11](https://www.korea.kr/news/policyNewsView.do?newsId=148954539) |
| 마약 운반 | [정책브리핑 카드뉴스 2024-06-11](https://www.korea.kr/multi/visualNewsView.do?newsId=148930130) |
| 해외 취업 감금 | [KTV·정책브리핑 2025-11-19](https://www.korea.kr/news/policyNewsView.do?newsId=148954930) |
| 스팸문자 전송 | [방통위·법무부·경찰청, 정책브리핑 2021-10-26](https://www.korea.kr/news/cardnewsView.do?newsId=148894762) |
| 송금·인출 대행 | [방송통신위원회 보도자료 2019-12-17](https://korea.kr/news/pressReleaseView.do?newsId=156366760) · [KTV·정책브리핑 2019-12-13](https://www.korea.kr/news/policyNewsView.do?newsId=148867501) |
| 채용 가장 판매원·다단계 | [고용노동부 보도자료 2013-05-22](https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=3624) |
| 성매매 유인 의심 구인광고 | [고용노동부 설명자료, 정책브리핑 2023-02-15](https://www.korea.kr/briefing/actuallyView.do?newsId=148911719) |
| 택배차 강매·대출 | [국토교통부, 정책브리핑 2024-06-21](https://www.korea.kr/news/policyNewsView.do?newsId=148930608) |

## 개인정보
- **텍스트:** AI로 보내기 전에 전화번호·계좌번호·카드번호·주민등록번호·이메일·메신저 ID를 자동으로 가립니다. 이름은 문맥 패턴으로 일부만 가리므로 빠질 수 있습니다.
- **이미지:** 사용자가 '개인정보를 가렸다'고 확인한 경우에만 AI로 보내 글자를 옮긴 뒤 다시 가립니다. 이미지 속 개인정보는 사용자 확인에 의존합니다.
- **AI 호출:** OpenAI 응답 저장 옵션을 끄고 호출합니다(`store=False`).
- **사례 저장(선택):** 사용자가 동의한 경우에만(기본 꺼짐) 가린 텍스트·구조화 결과·판정·시각을 비공개 저장소에 저장합니다. 보관 기한은 90일입니다. 기한이 지난 사례는 운영자가 검토 노트북(`notebooks/rule_review.ipynb`)을 실행할 때 지웁니다. 업체 조회 결과와 사업자등록번호는 저장하지 않습니다.
- 실제 개인정보를 넣지 마세요. 시연은 가상 데이터로 합니다.

## 직접 실행하기
로컬 Python 3.14에서 테스트했고, Streamlit Community Cloud에 배포했습니다.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 아래 값을 채움
streamlit run app.py
```

| 환경변수 | 필수 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | 예 | OpenAI API 키 |
| `MODEL_ID` | 아니요 | 기본 `gpt-6.2-sol` |
| `DATA_GO_KR_SERVICE_KEY` | 아니요 | 공공데이터포털 인증키(국세청·국민연금 조회). 없으면 해당 확인을 생략 |
| `HF_TOKEN`, `HF_DATASET_REPO` | 아니요 | 동의 사례 저장용 Hugging Face 토큰과 비공개 Dataset 이름 |
| `SESSION_CALL_LIMIT`, `DAILY_CALL_LIMIT` | 아니요 | 호출 상한(기본 15, 150) |
| `REASONING_EFFORT` | 아니요 | 추론 강도(기본 `low`) |
| `WORK24_AUTH_KEY` | 아니요 | 확장 기능(이번 버전 제외): 고용24 기업회원 인증키 |
| `DEV_FIXTURES` | 아니요 | 로컬 개발용. `1`이면 데모 샘플을 사람이 적어 둔 예시 추출값으로 판정(AI 호출 없음). 배포에서는 쓰지 않음 |

Streamlit Community Cloud에서는 같은 이름을 앱 Secrets에 넣습니다(`.streamlit/secrets.toml.example` 참고). 키는 코드에 넣지 마세요.

테스트:
```bash
pip install -r requirements-dev.txt
pytest
```

노트북(검증·규칙 검토):
```bash
python scripts/run_notebook.py notebooks/eval.ipynb         # 결과는 notebooks/results/ (AI 호출 결과는 캐시)
python scripts/run_notebook.py notebooks/rule_review.ipynb  # 사람의 승인 결정은 notebooks/review_decisions.json
```
Google Colab에서는 노트북 첫 셀이 이 저장소를 내려받고, 키를 Colab '보안 비밀'(`OPENAI_API_KEY`, `HF_TOKEN`, `HF_DATASET_REPO`)에서 읽습니다.

## 폴더 구조
```
app.py                  화면(Streamlit)
core/
  masking.py            AI 전송 전 개인정보 가리기
  extract.py            AI 구조화 추출(원문 인용), 이미지 글자 읽기
  verify_apis.py        공공 API 조회(국세청·국민연금), 같은 업체 조회 1시간 재사용
  rules_engine.py       규칙 엔진: 등급 결정
  questions.py          확인 질문
  pipeline.py           전체 흐름(1회차·2회차)
  storage.py            동의 사례 저장(Hugging Face 비공개 Dataset)
  evaluation.py · review.py  검증·규칙 검토 노트북에서 쓰는 함수
  limits.py · config.py · links.py · schema.py · samples.py
rules/rules.yaml        판정 규칙·근거 자료·신고처
data/samples/           데모 샘플(가상)과 미리 판독해 둔 결과
data/testset/           테스트셋(가상 53건), 외부 확인셋(정부 자료 예시 문구 4건)
notebooks/              검증(eval)·규칙 검토(rule_review) 노트북(Colab용), 결과는 notebooks/results/
scripts/                점검(공공 API·OpenAI·Hugging Face·반복 안정성), 노트북 생성·실행, 데모 이미지 생성
tests/                  자동 테스트
```

## 검증 결과 (합성 테스트셋, 규칙 v2.1.4, 2026-11-23)
`notebooks/eval.ipynb` 실행 결과입니다(결과 파일 `notebooks/results/eval_summary.json`). 사기 33건·정상 20건은 AI 도구로 만든 가상 공고입니다. 외부 확인셋 4건은 정부 자료의 예시 문구입니다.

| 방식 | 사기 탐지율 | 정상 오탐률 | 외부 확인셋 | 건당 비용 |
|---|---|---|---|---|
| 공고돋보기(AI 추출 + 규칙 엔진) | 100% (33/33) | 5% (1/20) | 3/4 | $0.014 |
| 키워드만(AI 없음) | 36.4% | 10% | 3/4 | $0 |
| 같은 모델에 위험 여부를 한 번 묻기 | 100% | 5% (1/20) | 3/4 | $0.0011 |

- AI가 근거로 인용한 문장 118개가 모두 원문에 있었습니다(인용 검증 100%).
- 규칙에서 해당 유형을 빼고 판정해도 28/33(84.8%)을 위험으로 잡았습니다(처음 보는 수법 대응). 약한 유형은 사칭 리뷰·직무 위장(각 1/3)입니다.
- 데모 샘플 ④를 5회 반복 판독해 등급이 매번 같았습니다(1회차 🟡 5/5, 2회차 🔴 5/5).
- 이 테스트셋에서는 위험 여부를 한 번 묻는 방식도 탐지율·오탐률이 같았고 비용은 더 적었습니다. 공고돋보기의 차이는 정확도보다 근거 문장 인용·검증, 공개된 규칙에 따른 일관된 등급, 업체 확인, 법적 결과·신고처 안내, 확인 질문과 2회차 판정에 있습니다.
- 규칙 v2.1.0의 정상 오탐은 20%였습니다. 검증 결과를 보고 규칙을 네 차례 고쳐(v2.1.1~v2.1.4, 변경 내용은 `rules/rules.yaml` changelog, 전후 결과는 `notebooks/results/`) 5%가 됐습니다. 같은 테스트셋을 보고 고쳤으므로 과적합 가능성이 있습니다. 표본(정상 20건)이 작아 수치는 참고용입니다.

## 한계
- AI가 원문 표현을 잘못 읽을 수 있습니다. 인용 확인과 규칙 판정으로 줄이지만 없앨 수는 없습니다.
- 정보가 부족한 정상 공고는 '확인 필요'로 나올 수 있습니다. 사업자번호가 없다는 이유만으로 위험하다고 하지 않습니다.
- 처음 보는 수법은 원칙 6축으로 대응하지만 모든 경우를 잡지는 못합니다.
- 국민연금 미가입·1인 사업장은 '확인 불가'로 표시합니다(위험이라는 뜻이 아님).
- 워크넷(고용24) 공식 공고 자동 대조는 기업회원 인증키가 필요해 이번 버전에서 뺐습니다(확장 예정).
- 검증은 합성 테스트셋(정상 20건 등)으로 했습니다. 표본이 작고 실제 분포와 다를 수 있습니다.
- 테스트셋은 AI 도구로 만든 가상 데이터라 실제 분포와 다를 수 있습니다.

## AI 활용
- **서비스:** OpenAI `gpt-6.2-sol` — 위험 신호 후보와 원문 인용 추출, 캡처 이미지 글자 읽기, 판정 이유 설명, 확인 질문 생성, 2회차 맥락 결합. 등급은 규칙 엔진이 정합니다.
- **개발:** Claude Code(Claude Opus 5.5) — 기획 문서·소개서·참가 신청문 초안과 문장 다듬기, 근거 조사 보조, 코드·테스트·데모 샘플 초안. 문제 정의, 설계 결정, 승인, 결과 검증은 대표자가 했습니다.

## Credits / Licenses

**오픈소스** (이름 / 라이선스 / 링크 / 용도)
| 이름 | 라이선스 | 링크 | 용도 |
|---|---|---|---|
| Streamlit 1.67.0 | Apache-2.0 | https://streamlit.io | 화면 |
| openai 3.57.0 | Apache-2.0 | https://github.com/openai/openai-python | AI 호출 |
| pydantic 2.14.4 | MIT | https://github.com/pydantic/pydantic | AI 구조화 결과 검증 |
| PyYAML 6.0.4 | MIT | https://pyyaml.org | 규칙·샘플 읽기 |
| requests 2.34.2 | Apache-2.0 | https://github.com/psf/requests | 공공 API 호출 |
| Pillow 13.0.0 | MIT-CMU | https://github.com/python-pillow/Pillow | 이미지 처리 |
| python-dotenv 1.2.4 | BSD-3-Clause | https://github.com/theskumar/python-dotenv | 로컬 환경변수 |
| huggingface_hub 2.4.0 | Apache-2.0 | https://github.com/huggingface/huggingface_hub | 동의 사례 저장 |
| pytest 9.2.0 (개발용) | MIT | https://github.com/pytest-dev/pytest | 자동 테스트 |
| pandas 3.1.1 (노트북) | BSD-3-Clause | https://pandas.pydata.org | 검증·검토 표 |
| nbformat 5.11.1 · nbclient 0.11.0 · ipykernel 7.4.0 (노트북 실행) | BSD-3-Clause | https://jupyter.org | 노트북 생성·실행 |

**이미지·폰트** (자료명 / 제작자·출처 / 라이선스)
- Noto Sans KR / Google Fonts(Noto 프로젝트) / SIL Open Font License 1.1 — 데모 캡처 이미지 글자 렌더링(`data/samples/demo_image_team_mission.png`, 글꼴 파일은 저장소에 없음)
- [Pretendard](https://github.com/orioncactus/pretendard) v1.3.9 / Kil Hyung-jin, jsDelivr CDN / SIL Open Font License 1.1 — 화면 본문·제목 글꼴(`.streamlit/config.toml`에서 CDN으로 불러옴, 글꼴 파일은 저장소에 없음)
- [IBM Plex Mono](https://fonts.google.com/specimen/IBM+Plex+Mono) / IBM, Google Fonts / SIL Open Font License 1.1 — 화면 라벨·메시지 패널 글꼴(CDN으로 불러옴)
- 화면 디자인 방향: [design-diversity](https://github.com/jmjmoon02-prog/design-diversity) `web-precision-fintech` 팩 / MIT — 색·글꼴·간격 규칙 참고(코드 복사 없음)

**데이터** (데이터명 / 제공기관 / 라이선스 / 기준일)
| 데이터명 | 제공기관 | 라이선스 | 기준일 |
|---|---|---|---|
| [사업자등록정보 진위확인 및 상태조회](https://www.data.go.kr/data/15081808/openapi.do) | 국세청(공공데이터포털) | 이용허락범위 제한 없음 | 조회 시점 |
| [국민연금 가입 사업장 내역](https://www.data.go.kr/data/3046071/openapi.do) | 국민연금공단(공공데이터포털) | 이용허락범위 제한 없음 | 조회 시점(응답의 자료생성년월) |

**판정 근거 자료** — 정부 자료 원문에 연결합니다. 정책브리핑 기사 텍스트의 이용 조건은 페이지마다 다릅니다(공공누리 제1유형 출처표시, 제4유형 출처표시·상업적 이용금지·변경금지, 일부는 표시 없음). 그래서 원문 문장은 바꾸지 않고 출처와 함께 짧게만 인용하며 비상업으로 씁니다. 언론 기사는 사실만 인용하고 출처를 밝혔습니다. 전체 목록은 `rules/rules.yaml`의 `evidence`에 있습니다.
- 위 '수법 10종' 표의 자료 12건
- [금융감독원, 정책브리핑 2022-10-07](https://www.korea.kr/news/policyNewsView.do?newsId=148906430) — 대포통장 처벌, 채용 전 신분증·계좌 요구 거절
- [고용노동부 설명자료, 정책브리핑 2019-02-19](https://www.korea.kr/briefing/actuallyView.do?newsId=148858514) — 거짓 구인광고 처벌
- [대법원 2021. 2. 25. 선고 2020두51587](https://www.law.go.kr/LSW/precInfoP.do?mode=0&precSeq=214213) — 업체명 미표시 구인광고
- [고용노동부 보도자료 2022-12-20](https://moel.go.kr/news/enews/report/enewsView.do?news_seq=14403) — 구인광고 게재 시 사업자 서류 확인
- [고용노동부 보도자료 2025-12-23](https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=18779) — 불법·거짓 구인 광고 원천 차단 대책
- 외부 확인셋(`data/testset/external_set.yaml`) 문구 4건은 아래 자료가 사기 공고 예시로 실은 문구를 바꾸지 않고 인용했습니다: [경찰청 카드뉴스 2024-04-23](https://www.korea.kr/multi/visualNewsView.do?newsId=148928265)(공공누리 제4유형), [KTV 2025-11-19](https://www.korea.kr/news/policyNewsView.do?newsId=148954930)(제4유형), [방통위·법무부·경찰청 2021-10-26](https://www.korea.kr/news/cardnewsView.do?newsId=148894762)(공공누리 표시 없음), [고용노동부 설명자료 2023-02-15](https://www.korea.kr/briefing/actuallyView.do?newsId=148911719)(제1유형)
- [경향신문 2022-02-21(경찰청 국가수사본부 자료)](https://www.khan.co.kr/article/202202211441001) · [한경 JOB&JOY 2026-05-13(한국직업정보협회 점검)](https://magazine.hankyung.com/job-joy/article/202605134054d) — 문제 정의 수치

**서비스** — Streamlit Community Cloud(배포), Hugging Face Hub(비공개 Dataset, 동의 사례 저장), OpenAI API. 각 서비스 이용약관을 따릅니다.
