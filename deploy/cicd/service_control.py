#!/usr/bin/python3 -I
"""Root-owned, fixed-resource broker. Never imports application code.

Install outside the writable checkout; see README.md. No arbitrary paths,
units, commands, environment configuration, or DB restore operation exist.
"""
import json
import http.client
import os
from pathlib import Path
import re
import sqlite3
import shutil
import subprocess
import sys
import time

CODE = Path('/opt/strategylab-v2')
DB = Path('/var/lib/strategylab/gaon-runtime.sqlite')
BACKUPS = Path('/var/backups/gaon-cicd')
UNITS = ('strategylab-gaon.service', 'gaon-web.service')
OPERATIONS = {f'{verb}-{name}': (verb, unit)
              for verb in ('stop', 'start')
              for name, unit in zip(('runtime', 'web'), UNITS)}
RUN_ID = re.compile(r'^[1-9][0-9]{0,19}-[1-9][0-9]{0,5}$')


def health():
    # Fixed loopback endpoint, no proxy, redirects, credentials or caller URL.
    connection = http.client.HTTPConnection('127.0.0.1', 8765, timeout=5)
    try:
        connection.request('GET', '/gaon/health')
        response = connection.getresponse()
        if response.status != 200:
            return False
        payload = json.loads(response.read(8192))
        return isinstance(payload, dict) and payload.get('status') == 'ok'
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=120, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}).stdout


def database():
    if DB.is_symlink() or not DB.is_file():
        raise ValueError('database unavailable')
    return sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True, timeout=10)


def inspect_database():
    with database() as db:
        version = db.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity != 'ok' or not isinstance(version, int):
        raise ValueError('database integrity or schema invalid')
    return {'schema_version': version, 'integrity': integrity}


def backup(run_id):
    if not RUN_ID.fullmatch(run_id):
        raise ValueError('invalid run identity')
    result = inspect_database()
    required = DB.stat().st_size + (DB.with_name(DB.name + '-wal').stat().st_size
                if DB.with_name(DB.name + '-wal').exists() else 0) + 128 * 1024 * 1024
    if shutil.disk_usage(BACKUPS.parent).free < required:
        raise ValueError('insufficient backup capacity')
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = BACKUPS / run_id
    destination.mkdir(mode=0o700)  # Never reuse/overwrite a previous backup.
    target = destination / 'gaon-runtime.sqlite'
    deadline = time.monotonic() + 120
    def progress(*_):
        if time.monotonic() > deadline:
            raise TimeoutError('backup deadline')
    with database() as source, sqlite3.connect(target) as copied:
        source.backup(copied, pages=256, progress=progress)
        if copied.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('backup integrity failed')
    target.chmod(0o600)
    return {**result, 'backup': str(target), 'backup_integrity': 'ok'}


def status(since):
    if not since.isdecimal() or not 0 <= time.time() - int(since) <= 86400:
        raise ValueError('invalid log interval')
    services = {}
    for unit in UNITS:
        raw = command(['/usr/bin/systemctl', 'show', unit,
                       '--property=ActiveState,MainPID,ActiveEnterTimestampMonotonic'])
        fields = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        pid = int(fields['MainPID'])
        try:
            cwd_ok = Path(f'/proc/{pid}/cwd').resolve(strict=True) == CODE
        except OSError:
            cwd_ok = False
        services[unit] = {'state': fields['ActiveState'], 'pid': pid,
                          'code_directory_matches': cwd_ok,
                          'active_since_monotonic': fields['ActiveEnterTimestampMonotonic']}
    raw = command(['/usr/bin/journalctl', '--since', '@' + since, '--no-pager',
                   '-o', 'json', '-n', '2000', '-u', UNITS[0], '-u', UNITS[1]])
    errors = 0
    for line in raw.splitlines():
        entry = json.loads(line)
        message = str(entry.get('MESSAGE', ''))
        if int(entry.get('PRIORITY', 6)) <= 3 or re.search(
                r'Traceback \(most recent|\bERROR\b|sqlite3\.OperationalError|ModuleNotFoundError', message):
            errors += 1
    # Deliberately never return raw logs: they may contain trading credentials.
    return {'services': services, 'recent_error_count': errors,
            'log_scan_limit': 2000, 'log_scan_since': int(since)}


def dispatch(args):
    if len(args) == 1 and args[0] in OPERATIONS:
        verb, unit = OPERATIONS[args[0]]
        command(['/usr/bin/systemctl', verb, unit])
        return {'operation': args[0], 'ok': True}
    if args == ['inspect']:
        return inspect_database()
    if len(args) == 2 and args[0] == 'backup':
        return backup(args[1])
    if len(args) == 2 and args[0] == 'status':
        return status(args[1])
    raise ValueError('operation denied')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        print(json.dumps(dispatch(sys.argv[1:]), sort_keys=True))
    except Exception:
        print(json.dumps({'ok': False, 'error': 'privileged_operation_failed'}))
        sys.exit(1)
