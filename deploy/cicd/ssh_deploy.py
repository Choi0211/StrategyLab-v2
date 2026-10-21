#!/usr/bin/python3 -I
"""Unprivileged forced SSH command. Fixed checkout, code-only rollback.

No root application execution, package installation, or database restore.
"""
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
try:
    import fcntl
except ImportError:  # Module can be inspected by Windows CI; deployment is Linux-only.
    fcntl = None
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

SHA = re.compile(r'^[0-9a-f]{40}$')
RUN = re.compile(r'^[1-9][0-9]{0,19}-[1-9][0-9]{0,5}$')
PRS = re.compile(r'^[1-9][0-9]{0,9}(,[1-9][0-9]{0,9}){0,19}$')
UNITS = ('strategylab-gaon.service', 'gaon-web.service')


@dataclass(frozen=True)
class Policy:
    code: Path = Path('/opt/strategylab-v2')
    state: Path = Path('/var/lib/gaon-deploy')
    enabled: Path = Path('/etc/gaon-deploy/enabled')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def run(args, *, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                          text=True, timeout=120,
                          env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}).stdout.strip()


class Controller:
    def call(self, operation, *args):
        return json.loads(run(['/usr/bin/sudo', '-n', '/usr/local/sbin/gaon-service-control', operation, *args]))

    def health(self):
        # Ignore proxy env and never send credentials outside loopback.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open('http://127.0.0.1:8765/gaon/health', timeout=5) as response:
                return response.status == 200 and json.loads(response.read(8192)).get('status') == 'ok'
        except (OSError, ValueError):
            return False


def schema(code):
    tree = ast.parse((code / 'src/gaon/runtime/migrations.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA_VERSION' for t in node.targets):
            value = ast.literal_eval(node.value)
            if type(value) is int:
                return value
    raise ValueError('schema declaration missing')


class Deployment:
    def __init__(self, policy=Policy(), controller=None):
        self.p = policy
        self.control = controller or Controller()

    def git(self, *args):
        return run(['/usr/bin/git', *args], cwd=self.p.code)

    def import_check(self):
        script = ("import pathlib,gaon; "
                  "assert pathlib.Path(gaon.__file__).resolve().parent == pathlib.Path('src/gaon').resolve()")
        run([str(self.p.code / '.venv/bin/python'), '-I', '-c', script], cwd=self.p.code)
        run([str(self.p.code / '.venv/bin/python'), '-I', '-m', 'pip', 'check'], cwd=self.p.code)

    def healthy(self, since, before=None):
        for _ in range(15):
            state = self.control.call('status', str(since))
            services = state['services']
            ready = all(services[u]['state'] == 'active' and services[u]['pid'] > 0
                        and services[u]['code_directory_matches'] for u in UNITS)
            if before:
                ready = ready and all(services[u]['pid'] != before[u]['pid'] for u in UNITS)
            if ready and self.control.health():
                if state['recent_error_count']:
                    raise ValueError('recent service errors')
                return state
            time.sleep(2)
        raise ValueError('readiness failed')

    def execute(self, target, run_id, prs, bundle):
        if not SHA.fullmatch(target) or not RUN.fullmatch(run_id) or not PRS.fullmatch(prs):
            raise ValueError('invalid deployment scope')
        result = {'schema_version': 1, 'target_sha': target, 'run_id': run_id,
                  'pr_numbers': [int(n) for n in prs.split(',')], 'started_at': stamp(),
                  'status': 'failed', 'stage': 'preflight', 'rollback_attempted': False,
                  'rollback_succeeded': False, 'db_restored': False, 'services': {},
                  'api_healthy': False, 'running_sha': None, 'db_schema_version': None}
        previous = None
        stopped = False
        try:
            if not self.p.enabled.is_file() or self.p.enabled.read_text().strip() != 'enabled':
                raise ValueError('server deployment disabled')
            if self.p.code.is_symlink() or (self.p.code / '.git').is_symlink() or not (self.p.code / '.git').is_dir():
                raise ValueError('symlink checkout denied')
            if Path(self.git('rev-parse', '--show-toplevel')).resolve() != self.p.code.resolve():
                raise ValueError('checkout root mismatch')
            if self.git('status', '--porcelain', '--untracked-files=no'):
                raise ValueError('tracked changes present')
            previous = self.git('rev-parse', 'HEAD')
            result['previous_sha'] = previous
            before = self.healthy(int(time.time()))['services']
            db = self.control.call('inspect')
            result['db_schema_version'] = db['schema_version']
            if db['schema_version'] != schema(self.p.code):
                raise ValueError('current schema incompatible')
            self.git('bundle', 'verify', str(bundle))
            self.git('fetch', '--no-tags', str(bundle), 'HEAD')
            if self.git('rev-parse', 'FETCH_HEAD') != target:
                raise ValueError('bundle SHA mismatch')
            # No server pip/apt install: dependency changes require a separately reviewed rollout.
            if self.git('diff', previous, target, '--', 'pyproject.toml', 'uv.lock', 'requirements.txt', 'requirements.lock'):
                raise ValueError('dependency change requires manual provisioning')
            changed = self.git('diff', '--name-only', previous, target).splitlines()
            protected = ('deploy_backups', '.venv', '.env')
            if any(name == item or name.startswith(item + '/') for name in changed for item in protected):
                raise ValueError('protected local state change')
            if 'src/gaon/runtime/migrations.py' in changed:
                raise ValueError('migration edits require manual rollout')
            old_schema = schema(self.p.code)
            target_text = self.git('show', target + ':src/gaon/runtime/migrations.py')
            declarations = [ast.literal_eval(n.value) for n in ast.parse(target_text).body
                            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA_VERSION' for t in n.targets)]
            if declarations != [old_schema]:
                raise ValueError('automatic schema changes prohibited')
            destination = self.p.state / 'backups' / run_id
            destination.mkdir(parents=True, mode=0o700)
            archive = destination / 'code.tar'
            self.git('archive', '--format=tar', '--output=' + str(archive), previous)
            result['code_backup_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
            result['code_backup'] = str(archive)
            result['database_backup'] = self.control.call('backup', run_id)
            result['stage'] = 'switch'
            stopped = True  # Even a partial stop must recover the old services.
            self.control.call('stop-web')
            self.control.call('stop-runtime')
            self.git('switch', '--detach', target)
            self.import_check()
            since = int(time.time())
            self.control.call('start-runtime')
            if self.control.call('inspect')['schema_version'] != old_schema:
                raise ValueError('post-start schema mismatch')
            self.control.call('start-web')
            result['stage'] = 'verify'
            observed = self.healthy(since, before)
            if self.git('rev-parse', 'HEAD') != target:
                raise ValueError('checkout drift')
            result.update(observed)
            result.update(status='success', stage='complete', api_healthy=True, running_sha=target,
                          running_sha_evidence='exact HEAD + fresh service PIDs + service cwd + editable import path')
        except BaseException as exc:
            result['error_type'] = type(exc).__name__
            # Never include exception strings, command stdout, environment or raw journal logs.
            if stopped and previous:
                result['rollback_attempted'] = True
                try:
                    self.control.call('stop-web')
                    self.control.call('stop-runtime')
                    self.git('switch', '--detach', previous)
                    self.import_check()
                    if self.control.call('inspect')['schema_version'] != schema(self.p.code):
                        raise ValueError('rollback schema incompatible: leave stopped')
                    since = int(time.time())
                    self.control.call('start-runtime')
                    self.control.call('start-web')
                    observed = self.healthy(since)
                    result.update(observed)
                    result.update(rollback_succeeded=True, running_sha=previous, api_healthy=True)
                except BaseException:
                    result['rollback_succeeded'] = False
                    result['manual_recovery_required'] = True
                    for operation in ('stop-web', 'stop-runtime'):
                        try:
                            self.control.call(operation)
                        except BaseException:
                            pass
        finally:
            result['finished_at'] = stamp()
        return result


def main():
    if fcntl is None:
        return 2
    os.umask(0o077)
    # forced command only, no arbitrary argv/shell interpretation.
    parts = os.environ.get('SSH_ORIGINAL_COMMAND', '').split()
    if len(parts) != 4 or parts[0] != 'deploy' or not SHA.fullmatch(parts[1]) or not RUN.fullmatch(parts[2]) or not PRS.fullmatch(parts[3]):
        return 2
    _, target, run_id, prs = parts
    policy = Policy()
    policy.state.mkdir(mode=0o700, exist_ok=True)
    if shutil.disk_usage(policy.state).free < 512 * 1024 * 1024:
        raise ValueError('insufficient transfer capacity')
    with (policy.state / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reports = policy.state / 'reports'
        reports.mkdir(mode=0o700, exist_ok=True)
        if (reports / (run_id + '.json')).exists():
            return 2
        with tempfile.TemporaryDirectory(dir=policy.state) as temporary:
            bundle = Path(temporary) / 'release.bundle'
            with bundle.open('wb') as output:
                size = 0
                while chunk := sys.stdin.buffer.read(1024 * 1024):
                    size += len(chunk)
                    if size > 256 * 1024 * 1024:
                        return 2
                    output.write(chunk)
            def interrupted(*_):
                raise InterruptedError('deployment interrupted')
            signal.signal(signal.SIGTERM, interrupted)
            signal.signal(signal.SIGHUP, interrupted)
            result = Deployment(policy).execute(target, run_id, prs, bundle)
            text = json.dumps(result, sort_keys=True)
            (reports / (run_id + '.json')).write_text(text + '\n')
            print(text)
            return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('{"status":"unknown","error":"deployment_transport_or_preflight_failed"}')
        sys.exit(1)
