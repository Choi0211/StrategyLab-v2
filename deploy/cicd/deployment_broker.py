#!/usr/bin/python3 -I
"""Root-owned deployment supervisor. Never executes checkout/venv code as root.

The caller can supply only SHA/run/PR identifiers and bundle bytes. The worker
executable, repository, runtime identity and all privileged resources are fixed.
"""
import importlib.util
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
try:
    import fcntl
    import pwd
except ImportError:
    fcntl = pwd = None

CODE = Path('/opt/strategylab-v2')
STATE = Path('/var/lib/gaon-deploy-root')
ENABLED = Path('/etc/gaon-deploy/enabled')
WORKER = Path('/usr/local/libexec/gaon-deploy-worker.py')
WORKER_STATE = Path('/var/lib/gaon-deploy-worker')
CONTROL = Path('/usr/local/libexec/gaon-service-control.py')
SHA = re.compile(r'^[0-9a-f]{40}$')
RUN = re.compile(r'^[1-9][0-9]{0,19}-[1-9][0-9]{0,5}$')
PRS = re.compile(r'^[1-9][0-9]{0,9}(,[1-9][0-9]{0,9}){0,19}$')
MAX_BUNDLE = 256 * 1024 * 1024
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
       'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}


class DeploymentBusy(Exception):
    pass


def acquire(lock, timeout=120):
    """Absorb short overlaps, but never occupy the deployment queue forever."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeploymentBusy('deployment_lock_timeout') from None
            time.sleep(min(1, remaining))


def metadata(args):
    if (len(args) != 4 or args[0] != 'deploy' or not SHA.fullmatch(args[1])
            or not RUN.fullmatch(args[2]) or not PRS.fullmatch(args[3])):
        raise ValueError('deployment operation denied')
    prs = [int(p) for p in args[3].split(',')]
    if prs != sorted(set(prs)):
        raise ValueError('noncanonical PR list')
    return args[1:]


def trusted(path, *, directory=False):
    """Do not load helpers/config through writable or symlinked ancestors."""
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted broker installation')
    if directory != path.is_dir() or (not directory and not path.is_file()):
        raise ValueError('invalid broker resource')


def github_json(endpoint):
    request = urllib.request.Request('https://api.github.com/repos/Choi0211/StrategyLab-v2/' + endpoint,
                                     headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'gaon-deploy-broker'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            raise ValueError('authorization redirect denied')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    # No redirects to caller-controlled hosts, credentials, or private-key reads.
    with opener.open(request, timeout=15) as response:
        if response.geturl() != request.full_url:
            raise ValueError('unexpected authorization redirect')
        data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError('oversized authorization response')
        return json.loads(data)


def authorize(target, prs, run_id):
    run_number, attempt = run_id.split('-')
    endpoint = 'actions/runs/' + run_number + '/attempts/' + attempt
    run = github_json(endpoint)
    if (run.get('id') != int(run_number) or run.get('run_attempt') != int(attempt)
            or run.get('head_sha') != target or run.get('head_branch') != 'main'
            or run.get('path') not in ('.github/workflows/gaon-production.yml',
                                      '.github/workflows/gaon-production.yml@main',
                                      '.github/workflows/gaon-production.yml@refs/heads/main')
            or run.get('event') not in ('push', 'workflow_dispatch') or run.get('status') != 'in_progress'):
        raise ValueError('workflow run identity mismatch')
    jobs = github_json(endpoint + '/jobs')['jobs']
    verified = [j for j in jobs if j.get('name') == 'Verify exact production SHA'
                and j.get('head_sha') == target and j.get('conclusion') == 'success']
    approved = [j for j in jobs if j.get('name') == 'Approved Gaon deployment (disabled until configured)'
                and j.get('head_sha') == target and j.get('status') == 'in_progress']
    if len(verified) != 1 or len(approved) != 1:
        raise ValueError('CI success and environment-approved running job required')
    if github_json('git/ref/heads/main')['object']['sha'] != target:
        raise ValueError('target is not current trusted main')
    matched = sorted(p['number'] for p in github_json('commits/' + target + '/pulls')
                     if p.get('merged_at') and p.get('merge_commit_sha') == target
                     and p['base']['ref'] == 'main'
                     and p['base']['repo']['full_name'] == 'Choi0211/StrategyLab-v2')
    if matched != [int(p) for p in prs.split(',')]:
        raise ValueError('merged PR evidence mismatch')


def identity():
    account = pwd.getpwnam('strategylab')
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise ValueError('runtime must not be root')
    return {'user': account.pw_uid, 'group': account.pw_gid, 'extra_groups': [], 'umask': 0o077}


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(value, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    fsync_directory(path.parent)


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def head(credentials):
    return subprocess.run(['/usr/bin/git', '--git-dir=' + str(CODE / '.git'), '--work-tree=' + str(CODE),
                           '-c', 'core.fsmonitor=false', 'rev-parse', 'HEAD'],
                          cwd=CODE, env=ENV, check=True, capture_output=True, text=True,
                          timeout=15, **credentials).stdout.strip()


class Session:
    def __init__(self, control, credentials, target, run_id, prs):
        self.control, self.credentials = control, credentials
        self.target, self.run_id, self.prs = target, run_id, prs
        self.journal = STATE / 'active.json'
        self.previous = None
        self.stopped = False
        self.recovering = False
        self.before = None
        self.schema_version = None
        self.since = int(time.time())
        self.started_at = datetime.now(timezone.utc).isoformat()

    def request(self, message):
        if set(message) != {'operation', 'args'} or not isinstance(message['args'], list):
            raise ValueError('invalid worker protocol')
        operation, args = message['operation'], message['args']
        if not isinstance(operation, str) or not all(isinstance(v, str) for v in args):
            raise ValueError('invalid operation types')
        if operation == 'prepare':
            if args and args[0] == self.target:
                raise ValueError('duplicate target deployment denied')
            if self.previous or self.recovering or len(args) != 2 or not SHA.fullmatch(args[0]) or not args[1].isdecimal():
                raise ValueError('invalid rollback checkpoint')
            if head(self.credentials) != args[0] or self.control.dispatch(['inspect'])['schema_version'] != int(args[1]):
                raise ValueError('rollback checkpoint mismatch')
            authorize(self.target, self.prs, self.run_id)  # Recheck before enabling service mutation.
            self.before = self.control.dispatch(['status', str(self.since)])['services']
            if not all(item['state'] == 'active' and item['pid'] > 0 for item in self.before.values()):
                raise ValueError('original services must be active')
            self.schema_version = int(args[1])
            save(self.journal, {'previous_sha': args[0], 'target_sha': self.target,
                               'run_id': self.run_id, 'prs': self.prs, 'stopped': False})
            self.previous = args[0]
            return {'ok': True}
        if operation in self.control.OPERATIONS:
            if args or not self.previous:
                raise ValueError('service mutation without checkpoint')
            if operation.startswith('stop-') and not self.stopped:
                save(self.journal, {'previous_sha': self.previous, 'target_sha': self.target,
                                   'run_id': self.run_id, 'prs': self.prs, 'stopped': True})
                self.stopped = True
        elif operation == 'backup':
            if args != [self.run_id] or self.recovering:
                raise ValueError('backup identity mismatch')
        elif operation == 'inspect':
            if args:
                raise ValueError('inspect arguments denied')
        elif operation == 'health':
            if args:
                raise ValueError('health arguments denied')
            return {'healthy': self.control.health()}
        elif operation == 'status':
            if len(args) != 1:
                raise ValueError('status arguments denied')
        else:
            raise ValueError('privileged operation denied')
        return self.control.dispatch([operation, *args])

    def observe(self, expected, *, fresh=False):
        if head(self.credentials) != expected:
            raise ValueError('root-observed HEAD mismatch')
        result = self.control.dispatch(['status', str(self.since)])
        for unit in ('strategylab-gaon.service', 'gaon-web.service'):
            item = result['services'][unit]
            if (item['state'] != 'active' or item['pid'] <= 0 or not item['code_directory_matches']
                    or (fresh and item['pid'] == self.before[unit]['pid'])):
                raise ValueError('root-observed service mismatch')
        db = self.control.dispatch(['inspect'])
        if db['schema_version'] != self.schema_version or (fresh and result['recent_error_count']):
            raise ValueError('root-observed schema or log error')
        if not self.control.health():
            raise ValueError('root-observed API failure')
        result['db_schema_version'] = db['schema_version']
        result.update(api_healthy=True, running_sha=expected,
                      running_sha_evidence='broker HEAD + service PID/cwd + loopback health + worker editable import')
        return result

    def worker(self, mode, target, bundle):
        parent, child = socket.socketpair()
        process = subprocess.Popen(['/usr/bin/python3', '-I', str(WORKER), mode, target,
                                    self.run_id, self.prs, str(child.fileno())],
                                   stdin=bundle, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   pass_fds=(child.fileno(),), start_new_session=True,
                                   cwd='/', env=ENV, **self.credentials)
        child.close()
        interrupted = False
        def interrupt(*_):
            nonlocal interrupted
            if not interrupted and mode == 'deploy':
                interrupted = True
                try:
                    process.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
        old_handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGTERM, signal.SIGHUP)}
        deadline = time.monotonic() + 1200
        parent.settimeout(15)
        try:
            with parent, parent.makefile('rwb') as channel:
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        raise TimeoutError('worker deadline')
                    if not select.select([parent], [], [], 1)[0]:
                        continue
                    line = channel.readline(65537)
                    if not line:
                        break
                    if len(line) > 65536 or not line.endswith(b'\n'):
                        raise ValueError('oversized worker message')
                    try:
                        result = self.request(json.loads(line))
                        response = {'ok': True, 'result': result}
                    except Exception:
                        response = {'ok': False}
                    channel.write((json.dumps(response) + '\n').encode())
                    channel.flush()
                process.wait(timeout=15)
            raw = process.stdout.read(65537)
            if len(raw) > 65536:
                raise ValueError('oversized worker report')
            result = json.loads(raw)
            if not isinstance(result, dict) or (process.returncode and result.get('status') == 'success'):
                raise ValueError('invalid worker report')
            return result
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)

    def execute(self, bundle):
        result = {'status': 'unknown', 'db_restored': False}
        try:
            result = self.worker('deploy', self.target, bundle)
            if result.get('status') == 'success':
                if not self.stopped or not self.previous:
                    raise ValueError('success without deployment checkpoint')
                result.update(self.observe(self.target, fresh=True))
            elif result.get('rollback_succeeded'):
                result.update(self.observe(self.previous))
        except BaseException:
            result = {'status': 'unknown', 'db_restored': False}
        if self.stopped and result.get('status') != 'success' and not result.get('rollback_succeeded'):
            self.recovering = True
            try:
                result.update(self.worker('recover', self.previous, subprocess.DEVNULL))
                if not result.get('rollback_succeeded'):
                    raise ValueError('worker recovery unsuccessful')
                result.update(self.observe(self.previous))
            except BaseException:
                result.update(rollback_succeeded=False, manual_recovery_required=True,
                              api_healthy=False, running_sha=None)
                for operation in ('stop-web', 'stop-runtime'):
                    try:
                        self.control.dispatch([operation])
                    except BaseException:
                        pass
        if result.get('status') != 'success' and not result.get('rollback_succeeded'):
            try:
                result.update(self.control.dispatch(['status', str(self.since)]))
            except Exception:
                result['services'] = {unit: {'state': 'unknown'} for unit in ('strategylab-gaon.service', 'gaon-web.service')}
            try:
                result['db_schema_version'] = self.control.dispatch(['inspect'])['schema_version']
            except Exception:
                result['db_schema_version'] = None
        result.setdefault('started_at', self.started_at)
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        result.update(target_sha=self.target, run_id=self.run_id,
                      pr_numbers=[int(p) for p in self.prs.split(',')], db_restored=False,
                      deployment_identity='strategylab', authorization='GitHub main + merged PR + approved CI run')
        save(STATE / 'reports' / (self.run_id + '.json'), result)
        if not result.get('manual_recovery_required'):
            self.journal.unlink(missing_ok=True)
        return result


def main():
    if fcntl is None or pwd is None or os.geteuid() != 0:
        return 2
    target, run_id, prs = metadata(sys.argv[1:])
    os.umask(0o077)
    for path in (WORKER, CONTROL, ENABLED):
        trusted(path)
    trusted(STATE, directory=True)
    if ENABLED.read_text().strip() != 'enabled':
        return 2
    credentials = identity()
    trusted(CODE.parent, directory=True)
    trusted(WORKER_STATE.parent, directory=True)
    for path in (CODE, CODE / '.git', WORKER_STATE):
        info = path.lstat()
        forbidden = 0o077 if path == WORKER_STATE else 0o022
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != credentials['user']
                or info.st_mode & forbidden):
            raise ValueError('unexpected runtime directory ownership or permissions')
    with (STATE / 'deploy.lock').open('a') as lock:
        acquire(lock)
        reports = STATE / 'reports'
        reports.mkdir(mode=0o700, exist_ok=True)
        trusted(reports, directory=True)
        if (STATE / 'active.json').exists() or (reports / (run_id + '.json')).exists():
            raise ValueError('unfinished deployment or repeated run')
        authorize(target, prs, run_id)
        spec = importlib.util.spec_from_file_location('gaon_fixed_service_control', CONTROL)
        control = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(control)
        # Copy stdin into root-only storage, then pass a read-only descriptor.
        # No caller path is opened and the ingress cannot race this copy.
        with tempfile.TemporaryDirectory(dir=STATE) as temporary:
            path = Path(temporary) / 'release.bundle'
            with path.open('xb') as output:
                size = 0
                deadline = time.monotonic() + 180
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([sys.stdin.buffer], [], [], remaining)[0]:
                        raise TimeoutError('bundle transfer deadline')
                    chunk = os.read(sys.stdin.fileno(), 1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BUNDLE:
                        raise ValueError('bundle size exceeded')
                    output.write(chunk)
            with path.open('rb') as bundle:
                result = Session(control, credentials, target, run_id, prs).execute(bundle)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get('status') == 'success' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except DeploymentBusy:
        print('{"status":"blocked_busy","error":"deployment_lock_timeout","db_restored":false}')
        sys.exit(1)
    except Exception:
        print('{"status":"unknown","error":"deployment_broker_rejected"}')
        sys.exit(1)
