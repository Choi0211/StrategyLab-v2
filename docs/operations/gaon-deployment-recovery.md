# 가온 배포 대기열과 복구 운영

## 2026-10-23 조사 범위

확인한 main은 `52709a02f90522e7bc216d6ad9eebe7e1289e62d`이다.
공개 GitHub Actions 화면에서 #7 (`39915802502`)은 사용자가 취소했고,
#8 (`39921362643`)은 `gaon-production` reviewer 승인을 기다린다.
#6의 재실행 실패는 `gaon-ci-39893801765-2` 아티팩트 부재다.
#260은 run ID 기반 CI 증거 이름으로 이 문제를 수정했다.
#259는 root-only 활성화 파일 내용을 비특권 Worker가 읽던 오류를 수정했다.
서버에 설치된 Worker 해시, 현재 서비스, DB, HEAD는 이번 클라우드 환경에서
검증하지 못했다. 서버 별칭 DNS가 없고, 사설 IP SSH 연결은 거부됐으며,
GitHub API는 403이었다. 사용자 설명을 서버 실측 결과로 취급하지 않는다.

## 대기열과 중복 요청

워크플로 전체의 전역 concurrency를 제거한다. 승인 대기 중인 옛 SHA가
새 main의 CI와 승인 요청을 막지 않는다. 실행 중인 배포를 취소하는
`cancel-in-progress`는 사용하지 않는다. 서버 root broker의 배타적 flock과
durable active journal이 실제 서비스 변경을 직렬화한다. 짧은 경합은 최대
120초 재시도로 흡수한다. 한도를 넘으면 `blocked_busy` /
`deployment_lock_timeout`으로 실패하며 기존 작업을 중단하거나 무한 대기하지 않는다.
잠금 획득 후 최신 main과 승인·CI를 다시 확인하므로 대기 중 오래된 SHA가
된 요청은 배포하지 않는다.

이전 승인 요청은 GitHub 화면에 남을 수 있다. 자동으로 승인을 수락하거나
실행을 취소하지 않는다. 오래된 요청을 승인해도 runner admission, 전송 직전
검사, broker 최초 인가와 서비스 변경 직전 인가에서 최신 main SHA가
아니면 거절한다. GitHub API 장애도 거절한다. main 변경 이후 이미 수행 중인
배포는 강제 종료하지 않으며, 다음 배포는 별도 승인과 최신 CI가 필요하다.
마지막 인가 이후의 main 변경을 원격 시스템과 원자적으로 묶는 것은 보장하지 않는다.

동일 target이 이미 checkout되어 있으면 `blocked_duplicate`로 종료한다.
서비스를 재시작하거나 DB 백업을 반복하지 않는다. HEAD 일치만으로 실제
서비스 정상 또는 배포 성공이라고 보고하지 않는다. 이 상태에서 복구가
필요하면 관리자가 기존 journal과 서비스 상태를 검토해야 한다.

## 자동 검증과 복구 경계

CI의 clean exact SHA, unit/integration 통과와 비어 있지 않은 실행 건수,
merged PR, 최신 main, Environment 승인, 활성화 설정을 모두 유지한다.
현재 venv import 경로와 `pip check`는 두 서비스 중단 전에 검사한다.
target의 Git pack/의존성 변경/보호 경로/DB 스키마 호환성을 검사하고,
코드 archive와 온라인 SQLite 백업·무결성 검사를 거친다.
현재 checkout과 다른 target을 적용한 뒤에도 import/의존성을 재검사한다.

두 가온 unit만 중지·시작한다. fresh PID, service cwd, exact HEAD,
고정 localhost health API, SQLite 스키마/무결성, 최근 오류 수를 확인한다.
부분 중지, import 실패, health 실패, disconnect에는 기존 코드 복구를 시도한다.
DB는 자동 복원하지 않는다. 복구 실패 시 두 unit을 중지 상태로 두고
`manual_recovery_required`와 journal을 보존한다. root SIGKILL/전원 장애는
자동 복구를 보장하지 않는다. 다음 배포는 journal로 차단한다.

실거래·MyMoneyGuard unit, 키, 위험 한도, Passkey 승인, 전략 승격 정책은
이 변경의 대상이 아니다. `.env`, `.venv`, `deploy_backups/`를 보존한다.

## GitHub에서 결과 확인

배포 실패는 Actions 실패와 error annotation으로 표시된다. GitHub의
Watch/Actions notification을 구독하면 계정 알림 정책에 따라 알림을 받는다.
별도의 외부 알림 서비스는 설정하지 않는다.

Actions Summary와 `gaon-deployment-<run>-<attempt>` 아티팩트의
`deployment.json`, `ci.json`, `gate.json`을 확인한다. admission 실패는
`superseded_main`, `invalid_ci_evidence`, `merged_pr_missing`,
`github_authorization_unavailable`로 기록한다. Worker 실패는 `failure_stage`와
예외 종류만 공개하며 원문 로그·명령 출력·환경 변수·키는 공개하지 않는다.
CI JSON에는 SHA, 실행 건수, 실패·오류·skip 수가 있고 배포 JSON에는
PR/SHA/실행 시각/서비스/API/DB 스키마/롤백 결과가 있다.

승인 대기 중에는 runner가 없으므로 배포 아티팩트가 아직 없다.
이 경우 Actions의 Waiting 및 pending deployment가 판단 근거다.
취소된 실행, 중복 거절, disabled, unknown은 성공으로 간주하지 않는다.
인증된 GitHub 연결은 Actions run → artifacts 목록 → ZIP download로
JSON을 읽는다. 명령 예시는 [배포 README](../../deploy/cicd/README.md)에 있다.

## 남은 관리자 작업과 활성화

이 문서는 운영 설치 또는 배포 성공을 증명하지 않는다. 새 PR이 CI를 통과하고
검토·병합된 뒤 [root helper 설치 절차](../../deploy/cicd/README.md)에 따라
승인된 SHA의 Worker와 broker를 root-owned 고정 경로에 함께 설치해야 한다.
checkout 코드 업데이트만으로 root helper는 교체되지 않는다. 기존 helper를
백업하고 소유권/모드/구문 검사 후 설치한다. 범용 sudo나 checkout ACL을
추가하지 않는다. 서버 전체 패키지 설치도 하지 않는다.

관리자는 서버 접근 경로, 두 unit의 실제 실행 상태, SQLite 무결성/스키마,
Git tracked 작업 트리, 기존 journal, helper 해시, 최소 SSH sudoers,
root-only 활성화 파일을 확인해야 한다. Environment required reviewers와
main branch 제한을 유지하고 SSH key/known_hosts 및 Tailscale OIDC/태그를
기존 최소 구성으로 확인한다. 이 PR은 Secrets나 활성화 변수를 변경하지 않는다.

승인된 배포만 해당 Environment에서 진행한다. 실제 배포 후 보고서와
서버 HEAD·fresh PID·API·DB 상태를 대조해야 한다. 연구/학습의 운영 작업
진행 여부는 별도 실제 관찰이 필요하며 health 응답만으로 완료로 표시하지 않는다.
지속적인 비정상 종료 감지나 호스트 모니터링 timer는 현재 설치·검증되지 않았다.
서버 접근과 관리자 승인이 확보되기 전에는 이를 자동 운영 완료로 보고하지 않는다.
