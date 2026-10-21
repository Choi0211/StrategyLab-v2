# Gaon 점검 PR 배포·재시작·검증·복구 절차

**검토용 절차이며 이번 작업에서는 실행하지 않았다. PR 병합 전 배포하지 않는다.**
저장소의 systemd 예시 경로를 기준으로 작성했다. 운영 담당자는 실제 경로·서비스 계정·
접근 통제·디스크 여유를 먼저 확인하고 다르면 명령을 그대로 실행하지 않는다.
Binance/MyMoneyGuard 서비스, API 키, 포지션, 운영 환경 파일, systemd/nginx 설정은 변경하지 않는다.

이 PR은 DB migration이나 의존성 변경이 없다. 레거시 개발 HTTP 승인/실행 경로는
의도적으로 403을 반환한다. 이 API에 의존하는 클라이언트는 별도 Passkey 개발 승인
절차를 구현하기 전까지 사용할 수 없다. 일반 chat/Paper API를 인터넷에 공개하려면
기존 인증 프록시/신뢰망 구성을 별도로 확인해야 한다.

## 1. 병합 후 사전 확인 — 아직 서비스 중단하지 않음

운영자가 승인된 커밋 SHA를 지정한다. 테스트는 운영 checkout/DB가 아닌 CI·격리된
클라우드 checkout에서 실행한다. release-check 명령을 운영 DB에 실행하지 않는다.

```bash
set -euo pipefail
cd /opt/strategylab-v2
TARGET_SHA='<병합 후 승인된 전체 커밋 SHA>'
PREVIOUS_SHA=$(git rev-parse HEAD)
test -z "$(git status --porcelain)"
git fetch origin main
git cat-file -e "$TARGET_SHA^{commit}"
git merge-base --is-ancestor "$TARGET_SHA" origin/main
df -h /opt/strategylab-v2 /var/lib/strategylab
sudo systemctl is-active gaon-web.service strategylab-gaon.service
```

로컬 변경이 있으면 중단하고 보존한다. `reset --hard`, `git clean`, 운영 키/환경값 출력은
하지 않는다. `PREVIOUS_SHA`와 `TARGET_SHA`를 배포 기록에 남긴다. 실제 서비스 설정이
저장소 예시와 다르면 운영 담당자가 기존 구성을 확인하며 새 설정으로 덮어쓰지 않는다.

## 2. Gaon만 중단하고 일관된 DB 백업

기존 점검 시간/접근 통제로 사용자 승인이 진행되지 않게 한 뒤 두 Gaon 서비스만 중단한다.
진행 중이던 연구 쓰기도 종료된 것을 확인한다. 아래 Python은 키나 테이블 내용을 출력하지 않는다.

```bash
sudo systemctl stop gaon-web.service strategylab-gaon.service
BACKUP_DIR="/var/lib/strategylab/backups/audit-$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 700 -o strategylab -g strategylab "$BACKUP_DIR"
sudo -u strategylab /opt/strategylab-v2/.venv/bin/python - "$BACKUP_DIR" <<'PY'
import sqlite3, sys
from pathlib import Path
backup = Path(sys.argv[1]) / 'gaon-runtime.sqlite'
with sqlite3.connect('file:/var/lib/strategylab/gaon-runtime.sqlite?mode=ro', uri=True) as source:
    with sqlite3.connect(backup) as target:
        source.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
backup.chmod(0o600)
print('Database backup verified')
PY
```

백업 실패 시 코드 교체를 하지 않고 기존 Gaon 서비스를 다시 시작해 중단 시간을 복구한다.
백업 디렉터리와 이전 SHA를 보존한다. DB/WAL 파일을 실행 중에 복사하거나 삭제하지 않는다.

## 3. 코드 교체와 시작

```bash
cd /opt/strategylab-v2
git switch --detach "$TARGET_SHA"
.venv/bin/python -m gaon.runtime.cli deployment-import-path-check \
  --expected-source /opt/strategylab-v2/src/gaon
sudo systemctl start strategylab-gaon.service
```

런타임이 유일한 schema migration owner다. 시작 로그와 아래 **읽기 전용** schema 확인이
성공한 다음 web을 시작한다. 이 PR의 schema는 48이며 이전/대상 버전의 호환성을 확인한다.
`db-check`/`health` CLI는 `RuntimeStateStore` 생성 시 migration을 실행할 수 있어, 동시에
살아 있는 운영 runtime에 별도 migration owner로 사용하지 않는다.

```bash
sudo -u strategylab /opt/strategylab-v2/.venv/bin/python - <<'PY'
import sqlite3
with sqlite3.connect('file:/var/lib/strategylab/gaon-runtime.sqlite?mode=ro', uri=True) as db:
    assert db.execute('SELECT MAX(version) FROM schema_version').fetchone()[0] == 48
print('Schema ready')
PY
sudo systemctl start gaon-web.service
sudo systemctl is-active strategylab-gaon.service gaon-web.service
curl --fail --silent --show-error http://127.0.0.1:8765/gaon/health
```

여기서 health의 `status=ok`만으로 전체 승인을 완료하지 않는다. 기존 HTTPS 운영 도메인에서:

1. 모바일 320~390px에서 로그인·전략 선택·긴 ID 표시를 확인한다.
2. 등록된 Passkey 로그인 성공 후 후보/버전 목록이 보이는지 확인한다.
3. 비로그인 `/gaon/admin/strategy/options` 요청은 403인지 확인한다.
4. 일반 `confirm=true` 활성화와 레거시 개발 승인 경로가 계속 403인지 확인한다.
5. 로그인/조회만으로 ACTIVE 전략이 바뀌지 않는지 기존 감사 기록으로 확인한다.
6. 실제 전략 활성화/롤백은 검증을 위해 임의 수행하지 않는다. 승인 테스트는 격리 DB에서 한다.
7. 기존 Gaon 로그에서 import, SQLite lock, schema 오류가 없는지 확인한다. 로그를 공유할 때
   키/토큰·사용자 대화·계좌 내용이 포함되지 않게 한다.

실제 Android/iOS Passkey 성공, 외부 데이터 공급, 운영 성과는 이 클라우드 PR 검증에
포함되지 않았다. 운영자가 확인한 항목만 배포 결과에 기록한다.

## 4. 실패 시 복구

먼저 **코드만** 이전 SHA로 되돌린다. 이 PR은 schema 변경이 없으므로 DB를 되돌릴 이유는
통상 없다. 배포 후 승인/연구 데이터를 없애는 DB rollback을 기본 복구로 사용하지 않는다.

```bash
sudo systemctl stop gaon-web.service strategylab-gaon.service
cd /opt/strategylab-v2
git switch --detach "$PREVIOUS_SHA"
.venv/bin/python -m gaon.runtime.cli deployment-import-path-check \
  --expected-source /opt/strategylab-v2/src/gaon
sudo systemctl start strategylab-gaon.service
# 앞의 읽기 전용 schema 확인 후:
sudo systemctl start gaon-web.service
curl --fail --silent --show-error http://127.0.0.1:8765/gaon/health
```

DB 손상이 별도로 입증되어 복원이 필요한 경우에만 담당자가 백업 이후 쓰기/승인 이력
손실을 평가하고 별도 승인한다. 두 Gaon 서비스가 중단된 상태에서 현재 DB도 보존하고,
검증된 백업을 SQLite backup API로 목적 DB에 복원한다. `.sqlite`만 덮어쓰거나 WAL을
임의 삭제하지 않는다. 복구 뒤 schema/integrity·Passkey 로그인·권한 경계를 다시 확인한다.
승인/세션/챌린지를 과거 상태로 되돌리는 보안 영향도 검토한다.

어느 단계에서도 `binance-*`, MyMoneyGuard 서비스나 포지션/키/운영 설정을 변경하지 않는다.
