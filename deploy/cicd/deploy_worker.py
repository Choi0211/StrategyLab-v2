#!/usr/bin/python3 -I
"""Root-installed worker, executed only as strategylab by deployment_broker.

No root application execution, package installation, or database restore.
"""
import ast
from contextlib import contextmanager
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
import socket
import subprocess
import sys
import tempfile
import time

SHA = re.compile(r'^[0-9a-f]{40}$')
RUN = re.compile(r'^[1-9][0-9]{0,19}-[1-9][0-9]{0,5}$')
PRS = re.compile(r'^[1-9][0-9]{0,9}(,[1-9][0-9]{0,9}){0,19}$')
UNITS = ('strategylab-gaon.service', 'gaon-web.service')


@dataclass(frozen=True)
class Policy:
    code: Path = Path('/opt/strategylab-v2')
    state: Path = Path('/var/lib/gaon-deploy-worker')
    enabled: Path = Path('/etc/gaon-deploy/enabled')


def stamp():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def atomic_operation():
    # Deliver disconnect signals only after a complete RPC/Git operation.
    # Otherwise an unread reply can desynchronize rollback, or a killed Git
    # child can leave an index lock halfway through checkout.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGHUP})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def run(args, *, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                          text=True, timeout=120, close_fds=True,
                          env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                               'GIT_TERMINAL_PROMPT': '0'}).stdout.strip()


class Controller:
    def __init__(self, channel):
        self.channel = channel

    def call(self, operation, *args):
        with atomic_operation():
            self.channel.write((json.dumps({'operation': operation, 'args': list(args)}) + '\n').encode())
            self.channel.flush()
            line = self.channel.readline(65537)
        if not line.endswith(b'\n') or len(line) > 65536:
            raise ValueError('invalid broker response')
        response = json.loads(line)
        if not response.get('ok'):
            raise RuntimeError('broker operation failed')
        return response['result']

    def health(self):
        return self.call('health')['healthy']


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
        if controller is None:
            raise ValueError('authenticated local broker channel required')
        self.control = controller

    def git(self, *args):
        return self.git_at(self.p.code, *args)

    def git_at(self, directory, *args):
        with atomic_operation():
            return run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                        '-c', 'core.attributesFile=/dev/null', '-c', 'diff.external=',
                        '-c', 'fetch.recurseSubmodules=false', '-c', 'submodule.recurse=false',
                        '-c', 'fetch.fsckObjects=true', '-c', 'transfer.fsckObjects=true', *args], cwd=directory)

    def receive_objects(self, target, bundle):
        # A cached target object can let fetch ignore corrupt incoming pack
        # bytes. Validate in a fresh, unprivileged quarantine without existing
        # objects/alternates before touching the live repository's object store.
        self.p.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.p.state) as temporary:
            quarantine = Path(temporary)
            self.git_at(quarantine, 'init', '--bare', '--quiet')
            self.git_at(quarantine, 'bundle', 'verify', str(bundle))
            self.git_at(quarantine, 'fetch', '--no-tags', str(bundle), 'HEAD')
            if self.git_at(quarantine, 'rev-parse', 'FETCH_HEAD') != target:
                raise ValueError('bundle SHA mismatch')
            if self.git_at(quarantine, 'cat-file', '-t', target) != 'commit':
                raise ValueError('target must be a commit')
            self.git_at(quarantine, 'fsck', '--strict', '--no-reflogs', target)
            self.git_at(quarantine, 'update-ref', 'refs/heads/release', target)
            self.git('fetch', '--no-tags', str(quarantine), 'refs/heads/release')
            if self.git('rev-parse', 'FETCH_HEAD') != target:
                raise ValueError('verified object transfer mismatch')

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
            # The root-owned broker already validated the 0600 enable marker.
            # The unprivileged worker cannot traverse its root-only parent.
            if self.p.code.is_symlink() or (self.p.code / '.git').is_symlink() or not (self.p.code / '.git').is_dir():
                raise ValueError('symlink checkout denied')
            if Path(self.git('rev-parse', '--show-toplevel')).resolve() != self.p.code.resolve():
                raise ValueError('checkout root mismatch')
            # Local filter/include directives can execute code or redirect Git.
            config = self.git('config', '--local', '--name-only', '--list').splitlines()
            if any(key.lower().startswith(('filter.', 'diff.', 'url.', 'include.', 'includeif.')) or
                   key.lower() in ('core.worktree', 'core.sshcommand', 'core.gitproxy') for key in config):
                raise ValueError('unsafe local Git configuration')
            if self.git('status', '--porcelain', '--untracked-files=no'):
                raise ValueError('tracked changes present')
            previous = self.git('rev-parse', 'HEAD')
            result['previous_sha'] = previous
            if previous == target:
                result.update(status='blocked_duplicate', reason='target_already_checked_out')
                return result
            result['stage'] = 'current_health'
            before = self.healthy(int(time.time()))['services']
            db = self.control.call('inspect')
            result['db_schema_version'] = db['schema_version']
            if db['schema_version'] != schema(self.p.code):
                raise ValueError('current schema incompatible')
            result['stage'] = 'bundle_validation'
            self.receive_objects(target, bundle)
            result['stage'] = 'compatibility'
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
            result['stage'] = 'current_imports_dependencies'
            self.import_check()  # Reject an already broken venv before stopping either service.
            result['stage'] = 'backup'
            destination = self.p.state / 'backups' / run_id
            destination.mkdir(parents=True, mode=0o700)
            archive = destination / 'code.tar'
            self.git('archive', '--format=tar', '--output=' + str(archive), previous)
            result['code_backup_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
            result['code_backup'] = str(archive)
            result['database_backup'] = self.control.call('backup', run_id)
            if self.git('rev-parse', 'HEAD') != previous or self.git('status', '--porcelain', '--untracked-files=no'):
                raise ValueError('checkout changed during preflight')
            result['stage'] = 'authorization_checkpoint'
            self.control.call('prepare', previous, str(old_schema))
            result['stage'] = 'switch'
            stopped = True  # Even a partial stop must recover the old services.
            self.control.call('stop-web')
            self.control.call('stop-runtime')
            self.git('switch', '--detach', target)
            result['stage'] = 'imports_dependencies'
            self.import_check()
            result['stage'] = 'restart'
            since = int(time.time())
            self.control.call('start-runtime')
            result['db_schema_version'] = self.control.call('inspect')['schema_version']
            if result['db_schema_version'] != old_schema:
                raise ValueError('post-start schema mismatch')
            self.control.call('start-web')
            result['stage'] = 'verify'
            observed = self.healthy(since, before)
            if self.git('rev-parse', 'HEAD') != target:
                raise ValueError('checkout drift')
            if self.git('status', '--porcelain', '--untracked-files=no'):
                raise ValueError('checkout content drift')
            result.update(observed)
            result.update(status='success', stage='complete', api_healthy=True, running_sha=target,
                          running_sha_evidence='exact HEAD + fresh service PIDs + service cwd + editable import path')
        except BaseException as exc:
            result['error_type'] = type(exc).__name__
            result['failure_stage'] = result['stage']
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
            if stopped and result['status'] != 'success':
                try:
                    result.update(self.control.call('status', str(int(time.time()))))
                except BaseException:
                    result['services'] = {unit: {'state': 'unknown'} for unit in UNITS}
                try:
                    result['db_schema_version'] = self.control.call('inspect')['schema_version']
                except BaseException:
                    result['db_schema_version'] = None
            result['finished_at'] = stamp()
        return result


def recover(deployment, previous):
    result = {'status': 'failed', 'rollback_attempted': True, 'rollback_succeeded': False,
              'db_restored': False, 'running_sha': None, 'api_healthy': False}
    try:
        for operation in ('stop-web', 'stop-runtime'):
            deployment.control.call(operation)
        deployment.git('switch', '--detach', previous)
        deployment.import_check()
        if deployment.control.call('inspect')['schema_version'] != schema(deployment.p.code):
            raise ValueError('rollback schema incompatible')
        since = int(time.time())
        deployment.control.call('start-runtime')
        deployment.control.call('start-web')
        result.update(deployment.healthy(since))
        result.update(rollback_succeeded=True, running_sha=previous, api_healthy=True)
    except BaseException:
        result['manual_recovery_required'] = True
        for operation in ('stop-web', 'stop-runtime'):
            try:
                deployment.control.call(operation)
            except BaseException:
                pass
    result['finished_at'] = stamp()
    return result


def main():
    if fcntl is None or len(sys.argv) != 6:
        return 2
    os.umask(0o077)
    mode, target, run_id, prs, channel_fd = sys.argv[1:]
    if mode not in ('deploy', 'recover') or not SHA.fullmatch(target) or not RUN.fullmatch(run_id) or not PRS.fullmatch(prs) or not channel_fd.isdecimal():
        return 2
    policy = Policy()
    policy.state.mkdir(mode=0o700, exist_ok=True)
    if shutil.disk_usage(policy.state).free < 512 * 1024 * 1024:
        raise ValueError('insufficient transfer capacity')
    with socket.socket(fileno=int(channel_fd)) as channel_socket, channel_socket.makefile('rwb') as channel, (policy.state / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deployment = Deployment(policy, Controller(channel))
        def interrupted(*_):
            # Ignore repeated disconnect signals while rollback is running.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            raise InterruptedError('deployment interrupted')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGHUP, interrupted)
        if mode == 'recover':
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            result = recover(deployment, target)
            print(json.dumps(result), flush=True)
            return 0 if result['rollback_succeeded'] else 1
        with tempfile.TemporaryDirectory(dir=policy.state) as temporary:
            bundle = Path(temporary) / 'release.bundle'
            with bundle.open('wb') as output:
                size = 0
                while chunk := sys.stdin.buffer.read(1024 * 1024):
                    size += len(chunk)
                    if size > 256 * 1024 * 1024:
                        return 2
                    output.write(chunk)
            result = deployment.execute(target, run_id, prs, bundle)
            text = json.dumps(result, sort_keys=True)
            print(text)
            return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('{"status":"unknown","error":"deployment_transport_or_preflight_failed"}')
        sys.exit(1)
