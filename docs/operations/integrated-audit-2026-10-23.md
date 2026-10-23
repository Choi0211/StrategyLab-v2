# 가온·Binance·MyMoneyGuard 통합 점검 — 2026-10-23

## 판정과 증거 범위

이 문서는 클라우드 개발 환경에서 수행한 조사 기록이다. VPS 운영 완료 판정이 아니다.
운영 DB, 계정, 포지션, 서비스 상태, 실제 배포 SHA는 확인되지 않았다.
원본 요청은 `/workspace/attachments/dfc5183f-52b9-4244-9062-c3ae2f8252da/붙여넣은 텍스트.txt`에 보존되어 있다.

## 후속 운영 연결 점검

실행 위치는 Linux 6.18.55 x86_64 클라우드 `/workspace`다. Windows 드라이브,
PowerShell/Task Scheduler 연결 도구와 사용자 SSH 설정이 없다. Tailscale 로컬 클라이언트도
없지만 이것만으로 플랫폼 VPN 상태를 단정하지 않는다. 기존 VPS `100.99.127.60:22`의 TCP
조회는 다시 errno 111(connection refused)이었다. 기본 SSH 설정 조회는 systemd include
소유권 오류로 실패했다. 전역 SSH 설정·인증·host key 정책을 변경하지 않았다.

사용자는 Windows PC가 사용 가능하나 주소/SSH 정보를 모른다고 확인했고, Windows 검증을
별도 PC Codex 작업으로 분리하도록 지시했다. 기존 task와 연결을 재사용하는 지시서를
`binance_ai_bot_2/tools/pc_archive_sync/WINDOWS_CODEX_TASK.md`에 작성해 GitHub에 올렸다.

GitHub API는 후속 확인 시 접근됐다. PR #261은 open/미병합, mergeable=true이고 리뷰 기록은
비어 있다. Ubuntu 3.11/3.12, Windows 3.12와 workflow 문법 검사가 모두 통과했다
(run `39939406797`). Tailscale probe는 skipped로 실제 연결 증거가 아니다.
배포 #8(run `39921362643`)은 verify 성공, deployment job은 `gaon-production` 승인 대기다.
Environment required reviewer가 존재하고 `prevent_self_review=false`이며 정책은 변경하지 않았다.
Environment 변수·secret 목록 조회는 integration 권한 403이어서 실제 host/port/인증 설정은
읽지 못했다. 키를 추출하거나 새 인증을 구성하지 않았다. VPS 실제 SHA·서비스·디스크는 미확인이다.

Archive Sync 수정 및 Windows 작업 지시서 PR:
https://github.com/Choi0211/binance_ai_bot_2/pull/2

브랜치 `fix/pc-archive-sync-path-containment`, HEAD
`f1226e7a9dd3a9c503a9d85892892d2160d6e508`.
일시 전송 실패→재시도→검증→ACK 회귀를 추가해 로컬 selftest 총 7개가 통과했다.
Actions run `39942446931`의 Ubuntu/Windows × Python 3.11/3.12 4개 job도 모두 통과했다.
이는 GitHub Windows runner의 코드 테스트이며 사용자 PC 로그인·Task Scheduler 검증은 아니다.
서버 삭제·실거래/인증 변경·PC 작업 재등록·서버 배포는 수행하지 않았다.

아래 첫 조사 시점의 접근 실패 기록은 이 후속 조사와 구분해 읽어야 한다.

## Windows Archive Sync 후속 검증 요청 처리

GitHub의 `tools/pc_archive_sync/WINDOWS_CODEX_TASK.md`를 먼저 확인했다. GitHub blob SHA
`2112daadfe6486b40bf2eac4029adae4b1431cf4`와 로컬 파일 hash가 같아 당시 원격 지시서와
동일함을 확인했다. 이번 작업도 Linux 클라우드에서 실행 중이며 Windows에 연결된 도구나
승인된 원격 호스트 정보가 추가되지 않았다. 현재 환경의 부족은 Windows 관리자 권한 거부가
아니라 **Windows 실행 세션/접속 경로 자체가 제공되지 않은 것**이다.

| 사용자 요청 | 이번 확인 결과 |
| --- | --- |
| 작업 스케줄러 등록·활성 상태 | Windows 접속 미제공으로 미확인; task 재등록 없음 |
| 마지막 실행·결과·로그·PC 보관 위치 | 실제 PC 값 미확인; 코드 기본값을 운영 값으로 간주하지 않음 |
| 기존 SSH/Tailscale 설정 | cloud에 사용자 SSH 설정·Tailscale 클라이언트 없음; 실제 PC 설정 미확인 |
| `100.99.127.60:22` 거부 원인 | 현재 장치 신원/주소부터 확인 필요; VPS sshd 장애로 확정하지 않음 |
| VPS 전체·디렉터리별 디스크 | 서버 접근이 없어 미측정; cloud 사용량으로 대체하지 않음 |
| 실제 PC↔VPS 전송·hash·retry·Manifest | 미실행; 기존 모의/local fixture 및 CI 결과와 구분 |
| 이미 이전된 자료·서버 잔존 비교 | 양쪽 실제 manifest/파일 접근이 없어 미실행 |
| Windows 로그인 자동 실행 보완 | 등록 상태·기존 인자 확인 전 변경 없음; 실제 로그인 증거 미확인 |
| 운영 보고서 | 이 절에 확인 사실·미완료 이유 기록 |
| 서버 삭제·거래 변경·Live 활성화 금지 | 해당 작업 모두 미실행 |

현재 cloud의 `ip route get 100.99.127.60`은 eth0 기본 게이트웨이를 선택했고 로컬 Tailscale
인터페이스는 없다. 플랫폼 외부 VPN 경로 유무는 이 관찰만으로 확정할 수 없다.
주소는 shared CGNAT 범위 `100.64.0.0/10`에 속하지만 그 자체는 Tailscale 장치 신원 또는
현재 주소의 증거가 아니다. 저장소 workflow의 고정 IP도 현재 장치 목록을 대신하지 못한다.
따라서 이번에는 주소가 미확인인 상태에서 새 SSH probe나 포트 탐색을 추가하지 않았다.
이전 TCP refusal은 경로에서 관측된 사실이며, 응답 주체가 실제 VPS인지는 미확인이다.

과거 성공 run `39784441708`을 step 단위로 재조회했다. verify는 성공했지만
Join Tailscale / Verify private endpoint / Transport 단계는 모두 skipped였다.
이 실행의 success는 실배포 또는 연결 성공 증거가 아니다. 실패 run `39893801765`도
download-artifact 단계 실패여서 SSH 거부 원인을 증명하지 않는다.

기존 PC 작업 지시서에 `tailscale status --json`에서 mymoneyguard peer 이름·현재 IP·Online을
확인한 후 ping/TCP/host key/인증을 차례로 구분하는 읽기 전용 절차를 추가했다.
기존 연결이 없으면 설치·재인증·ACL 변경·신규 SSH 시스템을 만들지 않는다.
수정은 기존 PR #2의 `daffcdd` 커밋으로 전달했다. PowerShell 예시는 현재 cloud에서 실행된
결과가 아니며 실제 장치에서 검증해야 한다. 코드 자체는 변경하지 않았다.

재개에 필요한 환경은 다음과 같다. 사용자 Windows PC의 기존 저장소를 연 로컬 Codex 실행
세션 또는 승인된 기존 원격 연결이 필요하다. 그 세션에서 기존 Tailscale peer 상태와 task를
직접 읽어야 한다. 확인된 peer에 대해서도 SSH가 불가하면 기존 VPS 관리 세션/콘솔의
읽기 전용 listener·tailscaled 상태가 필요하다. 새 비밀번호·키 값을 채팅으로 요청하지 않는다.

## A. 전체 현황과 체크리스트

| 우선순위 | 작업 | 상태 | 확인 근거 / 다음 조건 |
| --- | --- | --- | --- |
| P0 | 저장소 현황 | 부분 완료 | 4개 기존 체크아웃 조사, 시작 시 모두 clean |
| P0 | PR #261 코드·테스트 | 부분 완료 | 로컬 release 및 원격 Ubuntu/Windows CI 통과; 미병합·리뷰 없음 |
| P0 | GitHub PR·Issue·Actions 최신 상태 | 부분 완료 | API 접근 복구, PR #261 CI·배포 #8 승인 대기 확인; 전체 Issue 조사는 미완료 |
| P0 | VPS 서비스·HEAD·DB·백업·로그 조사 | 접근 권한 또는 승인 대기 | 사설 주소 SSH TCP 연결 거부, 기존 사용자 SSH 설정 없음 |
| P0 | 배포·롤백 운영 검증 | 미완료 | CI 결과, 관리자 helper 검토, VPS 접근 필요 |
| P0 | VPS 용량·inode 조사 | 접근 권한 또는 승인 대기 | 현재 측정 가능한 클라우드 파일시스템은 VPS와 다름 |
| P1 | 가온 웹 API | 부분 완료 | 격리 DB 로컬 실행 및 HTTP 확인, 운영 연동 미검증 |
| P1 | 대화·연구·RAG·스케줄러 | 부분 완료 | 구현·기존 테스트 존재; 실제 LLM·연구 작업 이력 미확인 |
| P1 | Binance 보호·Paper/Live 분리 | 부분 완료 | 모의 테스트 통과; 운영 설정·거래 내역 미확인 |
| P1 | MyMoneyGuard 연동 | 부분 완료 | 읽기 전용 스냅샷 어댑터·내보내기 테스트 확인 |
| P1 | Telegram 연동 | 부분 완료 | 통합 대화 테스트 확인; 실제 메시지 송수신 미실행 |
| P2 | LONG/SHORT 성과·승격 | 미완료 | 운영 체결·수수료·슬리피지·기간 외 표본 필요 |
| P2 | 화면·모바일·캐릭터 | 부분 완료 | Binance UI 회귀 테스트 통과; 실제 브라우저·단말 검증 미실행 |
| P3 | 저장공간 자동 관리 | 부분 완료 | 보고 전용 timer/unit 및 관리 코드 존재; 설치 여부 미확인 |
| P3 | Windows PC 이전 | 부분 완료 / 접근 대기 | 기존 클라이언트 발견·보완·호환성 통과; Windows/VPS 실제 이전 0건 |
| P3 | 재사용 개발 환경 | 부분 완료 | 의존성 설치·재설치·pip check 통과, 지침 초안 저장; publication 미실행 |

완료된 운영 작업으로 판정한 항목은 없다. 구현된 기능은 재구현하지 않았다.

## B. 코드·배포·테스트

### 소스 구분

| 소스 | 조사 시 SHA | 비고 |
| --- | --- | --- |
| `/workspace/StrategyLab-v2` | `9a0213f` | 기존 사용자 체크아웃 유지 |
| 원격 main | `52709a02f90522e7bc216d6ad9eebe7e1289e62d` | Git ls-remote 조사 시점, 최신값 재확인 필요 |
| PR #261 | `d457b2d7489e6072e203feeb289c1bb9c89d0a45` | `/workspace/validation/pr261`에 별도 검증 복사본 |
| `/workspace/binance_ai_bot` | `14f677d` | PR #55 병합 커밋 |
| `/workspace/binance_ai_bot_2` | `803f3af` | 별도 저장소, 운영 사용 여부 미확인 |
| `/workspace/StrategyLab` | `0dad5e4` | 주식 관련 레거시 코드; 운영 MyMoneyGuard와 동일하다고 단정하지 않음 |

PR: https://github.com/Choi0211/StrategyLab-v2/pull/261

PR 커밋은 조사한 main의 조상이 아니다. 이것만으로 PR의 병합 상태를 확정할 수 없다.
PR API와 Actions run `39921362643` 조회는 Forbidden이었다. Ubuntu/Windows 원격 CI 결과,
브랜치 보호·Environment 리뷰어·실제 배포 이력은 미확인이다. 토큰 부재로 단정하거나
기존 인증·승인·네트워크 정책을 우회하지 않았다.

### PR #261 검토

- 전역 workflow concurrency를 제거하여 승인 대기와 실행 직렬화를 분리한다.
- runner에서 main SHA를 확인하고 전송 직전 다시 확인한다. root broker도 독립 승인 검증을 유지한다.
- 현재 HEAD와 동일한 배포는 차단하며 서비스 재시작·백업·health 성공을 주장하지 않는다.
- root broker 잠금은 최대 120초 범위에서 재시도하며 실행 중 배포를 취소하지 않는다.
- 기존 venv import/dependency 검사 후 백업·중단으로 진행하고 실패 단계를 기록한다.
- 자동 DB 복원, 임의 의존성 설치, 스키마 자동 변경 허용은 추가하지 않는다.
- `deploy/cicd/README.md` 앞부분에는 여전히 전역 concurrency 설명이 남아 있어 실제 workflow와
  문서가 불일치한다. 문서 수정 대상으로 기록한다.
- root helper 변경은 서버의 기존 백업과 비교하고 별도 관리자 검토·설치 절차를 거쳐야 한다.
  이 조사에서 root helper를 설치하거나 배포 정책을 변경하지 않았다.

### 테스트 증거

| 검사 | 결과 | 증거 |
| --- | --- | --- |
| PR 배포 회귀 | 56개 통과 | `/workspace/validation/pr261-cicd.log` |
| 저장공간 관리 | 22개 통과 | `/workspace/validation/storage-tests.log` |
| Binance 보호·방향·UI | 149개 통과 | `/workspace/validation/binance-safety.log` |
| MyMoneyGuard 내보내기·조회·대화 | 46개 통과 | `/workspace/validation/binance-integration.log` |
| 의존성 설치·반복 설치 | 통과 | `/workspace/validation/setup-repeat.log`, `pip check` |
| 전체 release 검증 | 단위 2,288개, 통합 601개 완료; 통합 1개 skip, 실패·오류 0 | `/workspace/validation/pr261-release.json`, `.log` |
| PC Archive Sync | selftest 6개 통과 | `/workspace/validation/archive-selftest.log` |
| 서버↔클라이언트 Manifest | 50-byte 로컬 fixture 호환성 통과 | `/workspace/validation/archive-compatibility.json` |

배포·저장공간 테스트는 전체 suite에 포함될 수 있으므로 위 숫자를 전체 고유 테스트 수로 합산하지 않는다.
처음 release 명령은 archive에 Git 메타데이터가 없어 실행 전 실패했다. 검증 복사본에 원본
커밋 메타데이터를 연결하고 clean HEAD를 확인한 후 공식 명령을 재실행했다. 최초 Binance
선별 실행은 python-binance 미설치로 import 오류가 있었으며, 선언된 의존성 설치 후 재실행은 통과했다.
일부 테스트의 ResourceWarning, UTC API deprecation 경고는 별도 유지보수 후보이다.
모의 테스트의 주문 로그는 실제 거래소 주문 증거가 아니다.

실제 배포 SHA: 미확인. PR 병합·서버 배포·운영 서비스 재시작: 미실행.
StrategyLab-v2는 운영 문서만 추가했다. 후속 사용자 지시에 따라 binance_ai_bot_2의 기존
Archive Sync 클라이언트와 selftest를 수정했다. 의존성 선언·락파일은 변경하지 않았다.

## C. 웹

`127.0.0.1:18761`, 격리 DB `/workspace/validation/local-smoke.sqlite`로 가온 웹을 실행했다.
아래 조회는 모두 HTTP 200이었다.

- `/`: 서비스 discovery
- `/gaon/health`: `status=ok`
- `/gaon/storage/status`: 파일시스템 사용량 및 읽기 전용 상태
- `/gaon/research/mission?session_ref=onboarding-smoke`: `exists=false`, 주문·승격·전략 변경 없음
- `/gaon/paper/summary?family_id=onboarding-smoke`: 거래 수 0, 수익 지표에 빈 상태 반환

증거: `/workspace/validation/web-smoke.json`.
필수 인자가 없는 연구·Paper 조회는 HTTP 400으로 거부했다. 추측한 `/gaon/research/status`는
404였으며 discovery에 명시된 실제 경로로 수정해 확인했다.
운영 데이터 연결, 실제 로그인·Passkey, 모바일 브라우저, 콘솔, 캐릭터 애니메이션,
웹↔Telegram 운영 기록 공유는 미검증이다. UI 변경은 수행하지 않았다.

## D. 자동매매·가온 기능

Binance `directional_watch.py`에서 기존 R-Long 1분봉 연구 게이트와 v4 SHORT를 사용한다.
`strategy_v4/short_pattern_signal.py`에 `failed_rebreak && ma5_10_below` 조건이 있다.
이는 현재 운영 적용이나 성과를 증명하지 않는다. R-Long+00s60, BTC LONG 및 각 LONG 변형은
정확한 전략 ID·운영 버전·최근 체결을 대조해야 한다. 표본 부족 상태에서 전략을 승격하지 않았다.

가온의 `gaon.adapters.mymoneyguard`는 정제된 스냅샷을 읽는 어댑터다. 기본 경로는
`/opt/binance-trading/mymoneyguard_snapshot.json`이며 오래되거나 없는 데이터의 상태를 구분한다.
실제 KIS 주문 엔진·BXP 매도 실패·예수금·보유종목 동기화는 운영 접근 전 판정할 수 없다.
레거시 주식 코드에는 HolidayGuard 및 주문 재시도 호출이 있으나 import 시 거래 코드 실행
가능성을 배제하지 못하므로 운영 smoke로 실행하지 않았다.

대화 메모리·문서 수집·RAG·연구 결과 저장은 모델 파인튜닝 증거가 아니다. Ollama PC 연결,
외부 LLM fallback·비용 설정·실제 자율 연구 진행은 운영 구성과 이력을 확인해야 한다.
실거래 활성화, 포지션 생성·청산, 위험 한도 변경, 실제 Telegram 전송은 수행하지 않았다.

## E. 서버 용량·삭제 정책

VPS 정리 전/후 사용량: 미확인. 삭제 파일: 없음. 확보한 VPS 용량: 측정 불가.
클라우드 `/workspace`는 최초 overlay 약 32G, 사용 약 29M, 가용 약 30G로 표시됐지만
이 값은 VPS의 23GB 디스크 수치와 비교할 수 없다. 검증 환경은 의존성과 소스를 추가하므로
클라우드 사용량이 증가하는 것이 정상이다.

`gaon-storage-lifecycle.service`는 `--report`만 실행하며 삭제하지 않는다. timer 설치·활성 여부는
VPS에서 확인해야 한다. 관리 코드의 cold 분류는 backups 디렉터리의 최신 백업도 포함한다.
`--cleanup`은 manifest 포함 여부와 SHA-256을 확인하지만, 복구에 필요한 최근 백업 개수,
운영 필수성, 파일 종류·민감도, PC 열람·복구 성공까지 독립 검증하지 않는다.
따라서 체크섬 일치만으로 삭제 승인으로 간주할 수 없다. 기존 보고 전용 운영을 유지하고,
보존 정책·보호 경로·백업 복구 테스트를 먼저 검증해야 한다. 자동 정리 활성화는 미실행이다.

다음 운영 읽기 전용 조사: df/inode, 주요 디렉터리별 크기, journal/Docker/cache,
배포·DB 백업·연구 결과의 증가 추세, 서비스가 참조하는 경로. 후보는 A 운영 필수,
B 최근 복구 백업, C PC 이전 가능, D 재생성 캐시, E 삭제 후보, F 용도 불명으로 분류한다.
현재 접근 가능한 자료만으로 VPS 후보 목록을 만들어 내지 않는다.

## F. PC 이전

### 기존 기능 발견 및 보완

사용자가 제공한 커밋 `515109254fd00222e22eb3e53c899fd864a8ce78`과
`82d56fd8d7e7d9b3c1c0ef9e63aed49dbf8b5ad7`을 실제 Git 이력에서 확인했다.
`/workspace/binance_ai_bot_2/tools/pc_archive_sync/`에 `archive_sync.py`,
`archive_sync_selftest.py`, `register_task.ps1`이 이미 있다. 새 SSH 동기화 시스템은 만들지 않았다.

- 기존 클라이언트는 HTTP(S), file URL, 기존 mount/local 경로를 사용한다. SSH/Tailscale 연결을
  직접 생성하는 구현은 아니다. 실제 연결 경로는 Windows 작업 인자·mount·운영 설정에서 확인해야 한다.
- 기존 Task Scheduler 기본 이름은 `GaonArchiveSync`, 트리거는 **로그인 시**이다.
  부팅만 하고 로그인하지 않은 경우의 실행 보장은 구현되어 있지 않다.
- 기본 PC 보관 경로는 `%USERPROFILE%\GaonArchive`, ACK는 그 아래 `verified-manifest.json`이다.
  이는 코드 기본값이며 실제 PC 설정을 확인한 값이 아니다.
- 스케줄러 설정은 실행 제한 2시간, 실패 시 5분 간격 재시도 2회다. 등록 스크립트는 실행 로그
  파일을 별도로 구성하지 않으며 클라이언트는 stdout/stderr로 결과를 출력한다.
  작업 등록 상태·LastRunTime·LastTaskResult·Windows 이벤트 로그는 아직 미확인이다.
- 기존 selftest 5개가 먼저 통과했다. Manifest `/../../outside.txt`가 archive 밖을 가리키는
  취약점을 실제 경로 계산으로 재현했다. 기존 클라이언트에 `..`, Windows drive/UNC 및 잘못된
  경로 차단과 기존 symlink/junction을 통한 최종·staging 경로 이탈 차단을 추가했다.
  악성 경로 회귀 selftest를 포함해 6개 통과했다. 동시 파일시스템 변경까지 막는 별도 보안 경계나
  Windows 실기기 검증을 완료했다고 주장하지 않는다.
- 기존 서버 CLI로 COLD Manifest 생성 → 기존 PC 클라이언트 복사 → SHA-256·크기·내용 확인 →
  Verified Manifest 생성 → 재실행 중복 다운로드 생략 → 서버 `--cleanup --dry-run` 수용까지
  50-byte 비민감 로컬 fixture로 확인했다. 원본은 보존했다. schema_version 1 및
  `files[path,size_bytes,sha256]`, `root_paths`가 호환된다.
- Windows PowerShell·Task Scheduler·PC 원격 도구가 현재 Linux 환경에는 없다. PC 로그인부터
  실제 자동 동기화·무결성·로그까지의 운영 완료 판정은 접속 후 재개한다.

### 실제 이전 상태

이전 대상·PC 가용 공간·보관 위치: 미확인. 전송 0건, 0 bytes.
체크섬·열람·복구 검증: 미실행. 서버 원본 삭제: 없음.
PC 연결 후 운영 DB·현재 백업·키·환경 파일을 제외한 후보 목록부터 만든다.
암호화 전송 → SHA-256·개수·크기 검증 → 실제 열람·복구 검증 → 보존 목록 작성 순서로 진행한다.
검증된 복사 자체는 원본 삭제 승인이 아니다.
사용자의 추가 지시에 따라 서버 원본 삭제는 **별도 사용자 승인 전까지 수행하지 않는다**.
운영 DB·API 키·거래 기록·최근 복구 백업은 보존 대상이다.

PC 연결 후 먼저 기존 작업을 읽기 전용 조사한다. `Get-ScheduledTask -TaskName GaonArchiveSync`,
`Get-ScheduledTaskInfo -TaskName GaonArchiveSync`로 등록·활성·마지막 실행 결과를 확인하고,
실제 Action의 프로젝트 위치·ManifestSource·RemoteBase·ArchiveDir 및 기존 연결을 확인한다.
작업 인자에 비밀 URL이 있을 수 있으므로 전체 인자·credential 파일을 채팅에 덤프하지 않는다.
기존 설정과 이벤트 로그를 보존하고, 승인된 작은 비민감 파일만 실제 연결 시험에 사용한다.
서버 manifest와 PC ACK를 path+size+SHA-256으로 대조해 이전 완료/서버 잔존/실패/미이전을 나누고
양쪽 가용 공간·보관 크기를 따로 기록한다. 기존 task를 확인하기 전 재등록하지 않는다.

## G. 로드맵과 재개 조건

### 1주 이내

1. 환경 설정에서 `api.github.com` 허용 초안을 적용한 뒤 API를 재검사한다. Git HTTPS 읽기
   인증은 이미 동작하므로 새 PAT가 필요하다고 단정하지 않는다.
2. 기존 승인된 VPS VPN/프록시·관리자 계정·host key 경로를 연결한다. 채팅에 키 값을 보내지 않는다.
3. systemd 실행 경로·HEAD·작업 트리·venv·DB integrity/백업·서비스 로그·API·디스크를 읽기 전용 조사한다.
4. PR #261 Ubuntu/Windows CI·리뷰·현재 main·배포 #8을 대조한다. 테스트 실패 시 병합·배포하지 않는다.
5. root helper는 기존 관리자 절차로 검토 후 설치한다. 승인 gate를 거친 배포와 운영 API를 검증한다.

### 1개월 이내

- 운영 연구 마지막 실행·반복/중단 원인, LLM 오류·비용, 데이터 품질 및 연구 DB 상태를 연결한다.
- Paper/Live 설정과 체결 근거를 대조하고 전략별 수수료·슬리피지·MDD·기간 외 성과를 산출한다.
- 실제 계정 데이터가 연결된 웹·Telegram·모바일 UI와 오류·갱신 시각·알림 중복을 검증한다.
- 복구 요구에 맞는 백업 보존·경고·로그 한도를 정하고 PC 보관 파일럿을 수행한다.

### 장기

장기 작업 큐·재시도/중복 방지, 데이터 품질 기반 연구 정지, 승인 기반 전략 승격,
외부/PC LLM 상태·비용 기반 전환, PC 보관 재개·무결성 확인, 배포·장애 결과 관측을 개선한다.
기존 구현과 운영 증거를 먼저 대조하여 중복 개발을 막는다.

안전한 코드 조사·격리 테스트·문서화는 연속 수행 가능하다. Live 활성화·주문/청산·위험 한도,
민감 데이터 삭제·root 보안/배포 승인 정책·접근 권한 변경은 사용자 명시 승인 대상이다.

환경 초안에는 `install_script`, `start_skill`, API 허용 도메인을 저장했다. retained helper는
`/workspace/validation/install-audit.sh`, 고정 의존성은 `requirements-audit.txt`에 있다.
초안 저장은 실행 환경 적용·publication·새 task 검증 또는 운영 배포를 의미하지 않는다.
