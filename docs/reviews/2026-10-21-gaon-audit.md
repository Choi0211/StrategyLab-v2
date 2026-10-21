# Gaon 저장소 점검 — 2026-10-21

대상: `Choi0211/StrategyLab-v2`, 기준 커밋 `9a0213f7258b57decd8b1662c3e9a0ab60d8d91a`.
작업 브랜치: `audit/gaon-readiness-security`. 점검 환경은 `/workspace/StrategyLab-v2`의
격리된 Linux/Python 3.12.14 환경이다. 운영 서버에 접속하거나 서비스를 제어하지 않았다.
이 보고서는 코드·로컬 테스트 근거이며 운영 수익성·실거래 정상 동작 보증이 아니다.

## 최근 변경과 현재 구조

- 최근 PR #247~#255는 Paper 관측 원장, 중복 방지, 실패 분석 가설, 외부 백테스트
  결과 저장, 연구 메모리, 후보 등록과 MyMoneyGuard 읽기 전용 스냅샷 어댑터를 추가했다.
- Web/Telegram은 `LLMConversationBrain`을 공유한다. `autonomous_research_runtime.py`는
  bounded tick, BLOCKED 복구, 방향/근거/후보 생성, 승인 대기 상태를 다룬다.
  연구 후보 생성과 실거래 전략 활성화는 다른 권한이다.
- `learning/production.py`의 SQLite 학습 기록과 `runtime/research_learning.py`의
  외부 문서 JSON/JSONL 근거 저장이 병존한다. 근거 첨부는 주장의 진실성 인증이 아니다.
- 실제 레지스트리 활성화는 서버가 검증한 Passkey 서명, 정확한 actor/action/family/version,
  Origin/Host, 세션/CSRF, 일회성 챌린지를 사용하는 `control/passkey_*` 경로다.
  `knowledge/human_gated_promotion.py`의 HMAC 연구 계약은 이를 대체하지 않는다.
- 이 저장소의 모바일 화면은 관리자 로그인·등록 페이지다. 루트 HTTP 응답은 JSON
  서비스 안내이며, 전체 거래 대시보드 구현으로 볼 수 없다. Binance 대시보드는 별도 프로젝트다.

## 수정한 결함 — 우선순위순

| 우선순위 | 코드 근거와 문제 | 수정 및 검증 |
|---|---|---|
| P0 | `web_api.py`의 `/gaon/developer/approve`는 요청자가 제공한 `user_ref`, `confirm=true`만으로 HMAC 승인 티켓을 발급하고 `/execute`로 사용할 수 있었음. signing secret이 설정된 환경에서 위험 | 두 레거시 HTTP 쓰기 경로를 403으로 닫음. 개발 작업별 Passkey 승인 구현 전에는 재개하지 않음. CLI/연구 계약을 HTTP 인증으로 오인하지 않음. 위조 identity/confirm으로 어댑터가 호출되지 않는 회귀 테스트 추가 |
| P1 | WebAuthn 라이브러리의 `WebAuthnException`은 HTTP 경계에서 처리하던 `ValueError` 하위형이 아니었음. 잘못된 서명/등록이 정상 거부 응답 대신 예외로 빠질 수 있었음. clientData 구조도 여러 곳에서 중복 파싱 | 알려진 검증 실패를 `PermissionError`로 변환하고 엄격한 32바이트 client challenge 파서를 공유. 서명 검증과 user verification은 유지하며 잘못된 서명도 챌린지를 소진. malformed JSON/base64/response, 잘못된 서명·등록 회귀 검증 |
| P1 | `strategy_candidate_promotion.evaluate_run`에서 NaN/Infinity 비교가 실패 조건을 우회하고 후보를 APPLY_READY 심사 대상으로 만들 수 있었음 | 유한 수치, 정수 거래 수, 0.5~1 수익 종목 비율, run identity/규칙 구조 확인. NaN/±Infinity/bool/문자열/잘못된 payload 거부 테스트. ACTIVE 전환이나 자동 승격을 추가하지 않음 |
| P1 | 같은 모듈이 명시적 미국 연구 결과도 KR 패밀리로 분류 | 명시적 KR/US universe에 따라 패밀리를 분리하고 MULTI/미지원 범위 거부. 시장 metadata가 없는 과거 KR 트랙 데이터는 기존 KR 분류 유지. 실제 레지스트리/운영 전략의 이전·활성화는 하지 않음 |
| P1 | `research_learning.validate`가 반환된 KR/US 보고서를 실제 데이터 여부와 무관하게 `independent_market_evidence=True`로 표시 | provider source=`real:*`, 명시적 `fixture_backed=False`, 실제 사용 가능한 결과 조건 확인. fixture/실패 보고서는 `market_evidence_unverified`. 독립 근거가 있어도 `validated=False`, `automatic_promotion=False` 유지 |
| P1 | 오프라인 연구가 `validate_closed_bars`를 시간 경계 없이 호출하여 관측 시점에 아직 닫히지 않은 캔들도 학습 원장에 기록 가능 | 관측 시각과 봉 주기를 사용해 close time 확인. 미래/naive 관측 시각과 미지원 주기 거부. 1m/5m/15m/30m/1h/4h/1d/daily 지원. 거부 시 DB 테이블도 생성되지 않는 테스트 |
| P2 | 연구 BLOCKED 오류 응답에서 자동 주문/승격/config 변경 금지 보장이 빠짐 | 공통 차단 메시지에도 세 가지 보장을 표시. 기존 복구 시나리오의 실패 테스트를 실제 코드 수정으로 해결 |
| P2 | 모바일 관리자 화면에 403/세션 만료 후 이전 후보와 승인 버튼이 남고, 실패한 로그아웃을 완료로 오인할 수 있었음 | 인증 상태 초기화, 20분 클라이언트 만료 처리, 중복 로그인/승인 클릭 억제, 로그아웃 실패 명시, 승인 후 목록 갱신. select/긴 ID 반응형 개선 |
| P2 | `tests/test_strategy_deployment_directional_isolation.py`의 LONG/SHORT 격리 테스트 2개가 CI 검색 경로 밖에 있었음 | `tests/unit/`으로 이동해 CI에 포함 |
| P2 | 네트워크 없는 대화 회귀 테스트가 실제 검색/DNS/문서 서버에 의존 | 성공 경로의 외부 검색 및 DNS/HTTP 경계에 고정 응답 주입. 라우팅/감사/문서 파싱/안전성 assertion 유지. provider fallback와 양쪽 실패 검증은 `test_research_media_tools.py`에 유지 |

## 국내·미국 네 전략 확인 범위

사용자 지정 네 전략의 이름/ID는 이 저장소에서 확정할 수 없었다. **국내/미국 × 단타/중장기**
네 범주로 잠정 구분하여 확인했으며, 별도 전략 ID와의 대응은 미확인이다.

| 범주 | 확인한 코드 | 확인되지 않은 부분 |
|---|---|---|
| 국내 단타 | KR 미션/전략 계열, `multi_symbol.py`, `krx_real_pipeline.py`, 상대강도/평균회귀/돌파 등 후보·검증 코드 | 실제 단타 체결·비용·시간봉 공급·운영 성과. Yahoo daily 자료를 분봉 단타 검증으로 해석하면 안 됨 |
| 국내 중장기 | `daily_equity_research.py`의 KR 데이터→오프라인 연구→경험 원장 | 독립된 중장기 전략 사양/승인 버전/운영 연결/성과 |
| 미국 단타 | `global_market.py`의 미국 universe/provider, 시장 격리 계약 | 미국 intraday 전략의 실제 데이터·체결·검증·승인·배포가 모두 이어진 증거 |
| 미국 중장기 | US real daily bridge, 지표/one-bar walk-forward 연구, 오프라인 journal | 네 전략 중 어느 운영 ID인지, 중장기 보유/리밸런싱/검증 수익성 |

`indicator_hypotheses.py`와 방향별 레지스트리는 LONG/SHORT 계약을 제공하지만,
그것만으로 국내·미국 LONG/SHORT 4개 전략이 운영 중이라는 뜻도 아니다.
`indicator_walkforward.py`는 다음 봉 시가→종가의 **one-bar 연구 시뮬레이션**이며,
실제 체결 시뮬레이터나 장기 수익성 증명이 아니라는 코드 계약을 유지한다.
`mymoneyguard.py`는 주기적 JSON 스냅샷 조회뿐이다. 직접 KIS 연결·주문·Passkey 전달은 없다.
해당 운영 스냅샷이나 계좌·포지션·키는 이번 점검에서 읽거나 변경하지 않았다.

## 미완료·후속 검증 — 완료로 표시하지 않음

| 우선순위 | 항목 | 남은 작업 |
|---|---|---|
| P1 | 일반 chat/history/Paper API는 단일 운영자 신뢰망/외부 접근 통제 전제를 가짐. `user_ref`는 인증이 아님 | 인터넷 공개 전에 인증된 프록시·네트워크 격리 확인 필요. Paper 생산자 identity 및 수집 결과의 진위 인증은 별도 설계가 필요하며, 이 PR은 외부 생산자나 운영 설정을 바꾸지 않음 |
| P1 | Paper pass verdict/출처는 외부 보고 입력. 저장된 행과 fingerprint는 생산자 서명이나 실제 재현을 증명하지 않음 | 독립 재현/OOS/Paper forward 검증 및 생산자 인증 필요. APPLY_READY를 활성화·성과 인증으로 해석 금지 |
| P1 | 국내·미국 4개 실전 전략의 사양/운영 매핑 미확인 | 전략 ID, 시장·방향·주기·데이터 공급·비용·승인 버전의 명시적 대응 필요. 검증되지 않은 전략을 새로 활성화하지 않음 |
| P1 | 실데이터·검색·문서 취득 | 현재 클라우드에서 DuckDuckGo/Bing/NBER/Yahoo 요청은 proxy 403 또는 DNS 실패. 고정 응답 회귀 통과와 실서비스 접근 성공을 구분. 네트워크 변경 후 실제 취득 재검증 필요 |
| P2 | 기존 통합 테스트 1개가 skip | `test_gaon_production_conversation_hotfix.py`의 legacy single-symbol autonomous-learning continuation과 durable-owner ResearchMission 연결 한계. skip을 새로 추가하거나 통과로 계산하지 않음 |
| P2 | `research_learning.py` JSON/JSONL 저장과 SQLite learning 경로 병존 | 동시 파일 갱신·보관 정책·권한·메모리 통합은 별도 검증 필요. 파일 메모리 저장을 모델 가중치 학습이나 검증된 지식으로 표시 금지 |
| P2 | 모바일 기기별 Passkey/WebAuthn 성공 경로 | Chromium 테스트는 HTTP/WebAuthn 응답 대역을 사용. 실제 Android/iOS 생체 인증·RP 도메인·TLS·프록시·운영 DB 승인은 미검증 |

## 검증 결과

온보딩 기준 실행: 단위 2,211개 중 1개 실패, 통합 601개 중 5개 실패·1개 skip.
원인은 외부 네트워크 의존 경로와 BLOCKED 안전성 안내 누락으로 구분했다.

최종 검증 결과:

- `scripts/verify_release.py`: 종료 코드 0. Unit/Integration/CLI importability/필수 파일 모두 PASS.
- 최종 코드의 단위 suite: **2,225개 실행·전부 통과**, 51.076초.
- 통합 suite: **601개 실행 / 600개 통과 / 기존 1개 skip**. 추가 실패 없음.
- KR/US 후보 격리·학습 출처 검토 후 별도 21개 회귀 테스트도 통과.
- `pip check`: 의존성 충돌 없음. `git diff --check`: 통과.

- `scripts/check_mobile_admin.cjs`: Chromium 320/390/768px에서 가로 넘침 없음,
  로그인·목록 선택만으로 활성화 없음, 403 후 이전 목록/승인 비활성화,
  실패한 로그아웃의 정확한 안내, JS page error 없음. 실행:
  `CHROMIUM_PATH=/usr/bin/chromium node scripts/check_mobile_admin.cjs`.
  Playwright/Chromium은 이 선택적 검사에 필요하며 Python CI 의존성을 바꾸지 않았다.
- Passkey 거부/챌린지·Origin/CSRF/버전 격리 관련 기존 단위 검증 유지.
  전체 suite의 fixture 성과를 실제 전략 수익률로 표시하지 않는다.
- 실거래 서비스, Binance 코드, 키, 포지션, 운영 DB/환경 파일/systemd/nginx 설정 변경 없음.
  PR 병합 및 배포는 수행하지 않는다.

배포 검토용 명령과 복구 절차는 [운영 절차](../operations/GaonAuditDeployment.md)를 참고한다.
