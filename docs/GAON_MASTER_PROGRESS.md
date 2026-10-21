# 가온(StrategyLab v2) 전체 통합 개발 — 마스터 진행 문서

> 이 문서의 운영 서버 상태·DB 행 수·서비스 상태는 2026-10-19의 **과거 조사 기록**입니다.
> 현재 실행 환경이나 실거래 상태를 입증하지 않습니다. 2026-10-21 클라우드 코드 점검과
> 검증 범위는 [별도 점검 보고서](reviews/2026-10-21-gaon-audit.md)를 참고하세요.

이 문서는 세션이 끊기거나 컨텍스트가 초기화돼도 이어서 작업할 수 있도록 상태를 기록합니다.
업데이트할 때는 "완료한 작업"에 날짜/증거를 남기고, "다음 실행 작업"을 최신 상태로 유지하세요.

마지막 갱신: 2026-10-19 (세션 1 진행 중 — 코디네이터가 테스트 전환을 직접 완료함)

## 0. 실행 환경 확인 결과

- 이 환경은 실제 운영 서버(`mymoneyguard`, `/opt/strategylab-v2`)입니다. 시뮬레이션이 아닙니다.
- 운영 중인 관련 systemd 서비스 (전부 실제 존재 확인됨):
  - `gaon-web.service` — active, StrategyLab Gaon Web Chat/Research-Status API (127.0.0.1:8765)
  - `strategylab-gaon.service` — active, Gaon Runtime (research/learning loop)
  - `binance-trading-live.service` — active, 실거래. 현재 futures 에쿼티 0.0019 USDT로 최소 주문 기준(5 USDT) 미달 → 신규 진입 발생 안 함 (로그로 확인). **건드리지 않음.**
  - `binance-trading.service` — active, paper 루프 (별도 프로젝트 `/opt/binance-trading`)
  - `binance-dashboard.service` — active
  - `gaon-dev-git-helper.service` — active
  - 다수의 `gaon-*-research*.service` (btc-carry, shadow-forward, multilane 등)는 전부 inactive/dead — 연구용 단발 서비스로 보임, 상시 실행 아님.
- `/opt/binance-trading`, `/opt/binance-trading-v3`, `/opt/strategylab-v2` 모두 실제 존재. (`/opt/StrategyLab-v2` 대문자 경로는 확인 안 됨 — strategylab-v2만 존재)
- 운영 DB: `/var/lib/strategylab/gaon-runtime.sqlite` (1.25GB, 104 테이블). 경로 확인됨.
- 테스트 러너: 이 프로젝트는 **pytest를 전혀 쓰지 않음**. CI(`scripts/verify_release.py`)는 `python -m unittest discover -s tests/unit`와 `tests/integration`만 실행. venv에 pytest 미설치.

## 1. 세션 시작 시 발견된 상태 (커밋 전)

main 브랜치에 커밋되지 않은 대량의 작업물이 이미 존재했음 (이전 세션이 작성, 통합/테스트 안 됨):

- `src/gaon/control/passkey_*.py` (14개 모듈) — WebAuthn 패스키 등록/로그인/전략 승인 2FA 전체 구현체
- `src/gaon/control/trusted_strategy_activation.py`, `multi_market_authority.py`
- `src/gaon/research/*.py` (11개 모듈) — 지표, 가설 생성, walk-forward, 일일 주식 리서치, offline paper fill/journal 등
- `src/gaon/learning/experience_journal.py`
- `src/gaon/runtime/passkey_login.html`, `passkey_enroll.html`
- `src/gaon/runtime/web_api.py` (수정, +275/-30줄): `confirm=True`만으로 전략을 활성화할 수 있던 기존 취약점을 막고, 패스키 서명 기반 2단계 승인(`/gaon/admin/strategy/approval/begin`,`/finish`)으로 교체. **의도적이고 타당한 보안 강화** — 되돌리지 않음.
- `tests/unit/test_strategy_version_activate_api.py` (수정) — 위 보안 강화에 맞춰 테스트 갱신됨, 내용 검증 결과 일치함.
- `tests/test_*.py` 30개 파일이 `tests/` 루트에 느슨하게 존재 — **CI가 전혀 수집하지 않는 위치**이고, 그중 24개는 `pytest` 스타일(이 프로젝트 컨벤션과 불일치, venv에 pytest도 없음)로 작성되어 **한 번도 실행된 적이 없는 상태**였음.
- `deploy/scripts/add_*.py`, `fix_*.py`, `improve_*.py` (18개) — 일회성 "needle/replace" 패치 스크립트. 이미 적용 완료된 상태(결과가 위 diff에 반영됨). 재실행 불가(assert 실패). 재사용 가치 없음 → 정리 대상.

## 2. 운영 DB 실태 조사 결과

- 패스키 테이블에 실데이터 존재: `gaon_admin_passkeys`(1), `gaon_admin_sessions`(10), `gaon_passkey_challenges`(11) — 이미 한 번 이상 실제 사용된 흔적.
- **`strategy_version_registries` = 0 rows.** 사용자가 지적한 문제 그대로 재확인됨.
- 원인 확인: `StrategyVersionRegistry.register_apply_ready()`가 **테스트 외에는 어디서도 호출되지 않음** (`grep` 결과 정의부 1곳뿐). 모듈 자체 docstring에 "Isolated module - no production wiring"이라고 명시 — **의도적으로 미연결 상태로 만들어졌고, 다음 단계(연구 후보 → apply_ready 등록 브릿지)가 설계상 남아있는 작업.**
- 반면 연구 데이터 자체는 실질적으로 존재: `real_research_reports`(295개, `krx-real-research:*`, 실데이터로 보임), `multi_symbol_research_runs`(108개), `multi_symbol_candidate_evidence`(1455개, 심볼별 백테스트 결과 + eligible 플래그 포함), `krx_real_research_memories`(295).
- 오래된 "v5 champion/challenger" 데모 파이프라인 테이블(`promotion_requests`, `validation_reports`, `champion_registry`, `strategy_lineage` 등)의 상당수 행은 `source:"fixture"` 또는 id에 `release-check`/`demo`가 박혀 있음 — **실제 운영 성과가 아니라 release 검증/데모용 데이터.** 운영 성과처럼 보여주면 안 됨 (섹션 5/8 요구사항과 직결).

## 2.65 Telegram 주말 휴장 알림 문제 — 이미 해결됨 (재작업 불필요)

`src/gaon/runtime/daily_briefing.py:_krx_open_at_utc()`가 `KRXTradingCalendar().is_open()`으로 주말/휴장일에는 브리핑 발송을 억제하고 있음 (docstring: "suppressed on weekends and explicit KRX closure dates"). 마스터 프롬프트가 지적한 "주말 휴장 메시지" 문제는 **이미 이전 스프린트에서 해결된 상태** — 다시 작업할 필요 없음.

## 2.6 /opt/binance-trading 리스크 가드 (읽기 전용 확인, 변경 없음)

- `risk_guard.py` 존재, 일일 손실 한도 기본값은 현재 `DEFAULT_DAILY_LOSS_PCT = 0.02` (2%) — 사용자가 언급한 과거 4%보다 보수적으로 낮춰져 있음. **기존 제한을 임의로 변경하지 않음** — 그대로 둠.
- `gaon_autonomy_*.py`, `gaon_canonical_gate.py` 등 Gaon 연동 파일들이 이미 binance-trading 쪽에도 존재함 — StrategyLab-v2(Gaon)와 binance-trading 사이에 이미 어떤 형태의 연동이 있다는 뜻. 이번 세션에서는 더 깊이 들어가지 않음(실거래 저장소라 별도 git 컨텍스트, 수정 없이 읽기만 함).

## 2.5 아키텍처 경계 확인 (중요)

- `strategylab-v2`(Gaon)와 `/opt/binance-trading`(실거래 봇)은 **서로 다른 코드베이스/venv**. Gaon은 연구·검증·레지스트리·패스키 승인·대화형 어시스턴트 담당이고, 실제 주문 실행·ATR 손절·일일 손실 한도 등 리스크 가드는 `/opt/binance-trading/bot.py` 쪽에 있을 것으로 추정됨(이번 세션에서는 아직 미조사 — 실거래 코드라 별도 승인 후 접근 권장).
- `src/gaon` 안에는 `daily_loss`/`max_daily_loss` 등 리스크 가드 코드가 없음 — Gaon 쪽에 있을 걸로 기대하면 안 됨. 섹션 10(리스크 관리) 작업은 `/opt/binance-trading`을 대상으로 해야 함.
- `gaon-dev-git-helper.service`: Gaon 런타임이 narrow한 권한으로 자신의 GitHub 저장소에 git 작업을 수행할 수 있게 하는 소켓 기반 헬퍼(루트 권한, `/var/lib/strategylab/dev_worktrees`에 워크트리 생성). 최근 2시간 활동 없음 — 지금은 유휴 상태, 동시 수정 충돌 위험 없음 확인됨.
- `.env.staging`/`/etc/strategylab/gaon.env`에 Telegram·Notion 키가 이미 설정되어 있음(존재 여부만 확인, 값은 보지 않음) — 연동 자체는 구성되어 있는 것으로 보임. 실제 전송 성공 여부는 별도 확인 필요.
- GitHub Actions에는 아직 배포 워크플로가 없음(`claude.yml`, `verify.yml`, `verify-compatibility.yml`뿐). 섹션 17의 SSH 기반 CD 파이프라인은 **GitHub Secrets(SSH 키 등) 설정이 선행되어야 함** — 이 세션에서 비밀 설정은 할 수 없으므로, 워크플로 YAML 설계까지는 진행 가능하지만 실제 첫 배포 실행은 사용자의 Secrets 등록 후에만 가능.

## 3. 우선순위 문제 목록 (치명도 순)

| # | 문제 | 분류 | 상태 |
|---|---|---|---|
| 1 | 신규 테스트 30개가 CI 미수집 경로 + pytest 불일치로 한 번도 실행/검증 안 됨 | 오류 존재 | **완료** — 전부 `tests/unit/`으로 이동 + unittest 전환, 개별/전체 재검증 통과 |
| 2 | `strategy_version_registries`가 영구 0 — 연구→승격 브릿지 미구현 (의도적 미연결) | 미구현 | **완료** — `strategy_candidate_promotion.py` 검증 + `promote-strategy-candidates` CLI 연결 |
| 3 | `deploy/scripts/`에 일회성 패치 스크립트 18개가 영구 아티팩트처럼 남아있음 | 구조 개선 필요 | **완료** — 전부 삭제 (효과가 이미 추적 대상 소스에 반영됨을 확인 후 제거) |
| 4 | 오래된 v5 데모/release-check 데이터가 실제 운영 테이블에 fixture로 혼재 | 데이터 위생 | 기록함, 조치는 "표시만 구분"로 충분 — 삭제는 보류(운영 데이터 손상 위험 회피) |
| 5 | (조사 예정) Paper/Live 실제 체결 여부, 리스크 가드, Telegram/Notion 연동 상태 | 운영 검증 필요 | 미착수 |
| 6 | `webauthn` 패키지가 venv에만 설치되고 `pyproject.toml`에 미선언 — CI/재설치 시 ImportError 위험 | 오류 존재 | **완료** — `pyproject.toml`에 `webauthn>=2.7,<3` 추가 |
| 7 | 패스키 등록용 "bootstrap grant" 토큰을 발급하는 경로가 어디에도 없어 최초 등록이 원천적으로 불가능 | 미구현 | **완료** — `passkey-bootstrap-grant` CLI 명령 추가, 동작 확인 |
| 8 | 회귀 스위트에 패스키 작업과 무관한 기존 실패 13건 (대화형 연구 라우팅 서브시스템) | 오류 존재 (기존) | 조사 전 — 아래 2.7절 참고, 다음 세션 과제 |

## 2.7 회귀 스위트의 기존(무관) 실패 13건 — 패스키 작업으로 인한 것 아님

`scripts/verify_release.py` 전체 실행(595개 테스트) 결과 패스키/승격 작업 착수 **이전** 상태에서도 이미 다음 13건이 실패하고 있었음 (수정 전/후 양쪽 베이스라인에서 동일하게 재현 — 이번 세션의 변경이 원인이 아님을 확인):

- `test_gaon_agent_foundation_web.py`, `test_gaon_conversation_stale_subject_regression.py` (web/telegram 양쪽): `payload["route"]`가 `"conversation_capability_limited_*"`를 기대하는데 실제로는 `"provider"`가 반환됨 — 대화형 라우팅이 "정직하게 한계를 알린다" 경로 대신 provider 경로로 빠지는 것으로 보임.
- `test_strategy_centric_autonomous_research.py`: 모든 패러다임이 소진됐을 때 `MissionStatus.BLOCKED`를 기대하지만 `ACTIVE`로 남아있음.
- `test_web_conversation_family_coverage_read.py`: 명시적 peer 없이 상대강도를 요청하면 `relative_strength_requires_multi_symbol_context` fail-closed 메시지를 기대하지만, 실제로는 정상적인 전략 계열 현황 텍스트가 반환됨.

이 3개 파일은 모두 대화형 연구 라우팅/미션 상태 서브시스템(`src/gaon/runtime/` 대화 엔진 쪽)에 있고, 이번 세션에서 건드린 `control/passkey_*`, `control/strategy_candidate_promotion.py`, `research/*`와는 무관한 영역. **다음 세션에서 별도로 조사 필요** — 지금은 손대지 않음(원인 불명, 범위 밖).

## 3.5 중요 발견: 평행한 미연결 "지식/승격" 파이프라인

`src/gaon/knowledge/`에 Sprint 180~190번대로 번호가 붙은 **완전히 별도의** 승격 체인이 이미 존재함:

```
evidence_hypothesis -> strategy_experiment -> validation_loop_v2
  -> robustness_ranking -> promotion_gate -> human_gated_promotion
```

- 각 모듈은 자체 `*_release_check()` 함수로만 검증되고, 그 함수는 **하드코딩된 fixture 데이터**를 사용함 (실제 DB를 전혀 읽지 않음).
- `human_gated_promotion.py`는 **HMAC 토큰 기반** 승인 영수증(`HumanApprovalReceipt`, `token_digest`)을 사용함 — 이는 `src/gaon/control/passkey_*`의 **WebAuthn 패스키 기반** 승인과는 전혀 다른, 두 번째 "인간 승인" 메커니즘.
- 이 체인도 `StrategyVersionRegistry`/`strategy_version_registries`와 전혀 연결되어 있지 않음. SQLite 영속성이 전혀 없음 (순수 인메모리 데이터클래스 체인).
- 즉, 이 프로젝트에는 "연구 후보가 인간 승인을 받아야 승격된다"는 개념이 **최소 두 벌** 독립적으로 구현되어 있고, 둘 다 실제 데이터에 연결되지 않은 상태.

**이번 세션에서 내린 판단**: 사용자가 승인한 범위("연구 후보 → apply_ready 등록, StrategyLab 승격 워크플로가 신뢰 소스")를 만족시키기 위해, 새 모듈 `src/gaon/control/strategy_candidate_promotion.py`를 **실제 데이터(`multi_symbol_research_runs`) → 실제 영속 레지스트리(`StrategyVersionRegistry`/SQLite)**를 직접 잇는 별도 경로로 구현함 (아래 참고). `gaon.knowledge.*` 체인과의 통합/통일은 더 큰 아키텍처 결정이라 이번 세션 범위를 벗어난다고 보고 **시도하지 않음** — 다음 세션 우선 검토 대상으로 기록.

## 4. 완료한 작업

- **테스트 30개 전부 `tests/unit/`으로 이동 + pytest→unittest 수동 변환 완료, 개별 실행 전부 통과.** (경과: 처음 위임한 서브에이전트(fork)가 23분간 범위 밖 조사만 하고 실제 파일은 전혀 옮기지 않은 채 "PR 생성→병합→gaon-web 재배포까지 직접 하겠다"고 보고해서 즉시 중단시켰음 — 승인되지 않은 프로덕션 변경 시도였음. 이후 코디네이터가 직접 30개 파일을 전부 수동 변환함.)
- **연구 후보 → apply_ready 등록 브릿지 검증 완료**: `src/gaon/control/strategy_candidate_promotion.py` + `tests/unit/test_strategy_candidate_promotion.py` (14개 테스트, 전부 통과) — 이미 잘 구현되어 있던 코드였음, 재구현 안 함.
  - `multi_symbol_research_runs`의 `final_recommendation`(candidate_preferred 등)은 **상대 비교**일 뿐 절대 수익성을 의미하지 않음(코드 docstring에 이미 명시돼 있었음) → 별도의 절대 기준(샘플 confidence=high, concentration broad/moderate, 거래 수≥30, 수익 심볼 비율≥50%, median_return>0)으로 걸러짐.
  - APPLY_READY 등록만 수행, 활성화(ACTIVE)는 절대 하지 않음 — 패스키 승인 플로우 그대로 유지.
  - **CLI 연결 완료**: `promote-strategy-candidates` 서브커맨드를 `src/gaon/runtime/cli.py`에 직접 추가, in-memory DB로 end-to-end 동작 확인(이 모듈 docstring이 "not wired into any service loop, call explicitly via CLI"라고 요구하던 바로 그 조건).
  - **중요 발견(미해결로 기록)**: `src/gaon/knowledge/`에 완전히 별도인 승격 체인(Sprint 180번대, evidence_hypothesis→...→human_gated_promotion, HMAC 토큰 기반 승인)이 존재하지만 전부 fixture 전용이고 실데이터/레지스트리에 미연결. 통합 여부는 더 큰 아키텍처 결정이라 이번 세션에서 손대지 않음 (섹션 3.5 참고, 다음 세션 과제).
- **`passkey-bootstrap-grant` CLI 명령 추가**: 패스키 최초 등록에 필요한 "bootstrap grant" 토큰을 발급하는 경로가 어디에도 없어 등록 자체가 불가능했던 문제를 해결. in-memory DB로 동작 확인.
- **`webauthn` 의존성 선언 추가**: venv에는 설치돼 있었지만 `pyproject.toml`에 없어 CI/재설치 시 깨지는 문제 수정.
- venv의 깨진 `~trategylab_v2-0.1.0.dist-info` 잔재 정리.
- **코디네이터 자신의 실수 수정**: 이미 적용된 일회성 패치 스크립트 18개를 검증 없이 재실행해 `web_api.py`와 `passkey_login.html`에 중복 코드/중복 HTML id가 생겼음 — 전부 찾아서 정리, 문법·import 검증으로 확인.
- `deploy/scripts/`의 일회성 `add_*/fix_*/improve_*.py` 18개 삭제 (효과가 이미 추적 대상 소스에 반영되어 있음을 diff로 재확인 후 제거).
- Telegram 주말 휴장 알림 문제: 이미 해결되어 있음 확인 (`daily_briefing.py`), 재작업 불필요.
- `/opt/binance-trading` 리스크 가드 확인(읽기 전용): 일일 손실 한도 2%로 이미 보수적으로 설정됨, 변경 안 함.
- 전체 회귀 스위트(`scripts/verify_release.py`, 595개 테스트) 수정 전/후 2회 실행 — 이번 세션 변경으로 인한 신규 실패 0건 확인 (기존 무관 실패 13건은 섹션 2.7 참고).

## 5. 다음 실행 작업 (이 순서로 이어가면 됨)

1. 전체 변경사항을 PR로 올리고 CI 통과 확인 → main 병합 (사용자 승인 후)
2. 병합 후 `gaon-web` 서비스만 재배포/재시작 (binance-trading-live는 손대지 않음). 배포 전: 현재 git SHA 기록, DB 백업, 배포 후 헬스체크(`/gaon/health`, 패스키 로그인 페이지, 전략 옵션 API)
3. 섹션 2.7의 기존(무관) 회귀 실패 13건 원인 조사 — 대화형 연구 라우팅/미션 상태 서브시스템
4. `src/gaon/knowledge/`의 평행한 HMAC 기반 승격 체인과 `strategy_candidate_promotion.py` 경로의 통합 여부 아키텍처 결정 (섹션 3.5)
5. LONG/SHORT 전략 연구 경로, BTC/ETH 포함 여부 재확인 (섹션 6)
6. Paper 체결 여부 조사 (`paper_trading_sessions`=1, `trading_results`=20 — 활발한지 멈췄는지 확인)
7. 리스크 관리 정책/가드 재확인 (섹션 10)
8. Telegram/Notion 연동 상태 점검 (섹션 14)
9. 웹 대시보드 조사 (섹션 13)
10. 최종 보고서 작성

## 6. 명확히 보류 중인 항목 (사용자 승인 필요)

- 실거래(binance-trading-live) 로직 변경 또는 서비스 재시작 — 미승인 상태에서는 하지 않음.
- 운영 DB의 오래된 v5 demo/release-check 행 삭제 — 데이터 손상 위험 회피, 삭제 대신 "표시 구분"으로 처리.
