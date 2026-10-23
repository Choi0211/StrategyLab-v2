"""Runner-side admission; the root broker independently repeats authorization.

Only fixed error codes are published. GitHub CLI output/errors may contain
credentials or infrastructure details and must never enter reports.
"""
import json
import os
from pathlib import Path
import subprocess
import sys


class Denied(Exception):
    pass


def github(arguments):
    try:
        result = subprocess.run(['gh', *arguments], check=True, capture_output=True,
                                text=True, timeout=30)
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise Denied('github_authorization_unavailable') from None


def latest(target, repository):
    reference = github(['api', f'repos/{repository}/git/ref/heads/main'])
    if reference.get('object', {}).get('sha') != target:
        raise Denied('superseded_main')


def admit(directory, *, latest_only=False):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    target, repository = os.environ['GITHUB_SHA'], os.environ['GITHUB_REPOSITORY']
    result = {'target_sha': target, 'status': 'blocked', 'reason': 'invalid_ci_evidence'}
    try:
        latest(target, repository)
        if not latest_only:
            ci = json.loads((root / 'ci.json').read_text())
            suites = ci.get('suites', {})
            if (ci.get('status') != 'passed' or ci.get('sha') != target
                    or ci.get('source_dirty') is not False
                    or set(suites) != {'unit', 'integration'}
                    or not all(s.get('passed') is True and s.get('executed', 0) > 0
                               and s.get('failures', 0) == 0 and s.get('errors', 0) == 0
                               for s in suites.values())):
                raise Denied('invalid_ci_evidence')
            records = github(['pr', 'list', '--repo', repository, '--state', 'merged',
                              '--base', 'main', '--limit', '100', '--json', 'number,mergeCommit'])
            prs = sorted({p['number'] for p in records
                          if (p.get('mergeCommit') or {}).get('oid') == target
                          and type(p.get('number')) is int and p['number'] > 0})
            if not prs:
                raise Denied('merged_pr_missing')
            with open(os.environ['GITHUB_ENV'], 'a') as output:
                output.write('PR_NUMBERS=' + json.dumps(prs) + '\n')
                output.write('DEPLOY_PRS=' + ','.join(map(str, prs)) + '\n')
            enabled = os.environ.get('DEPLOY_ENABLED') == 'true'
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('ready=' + str(enabled).lower() + '\n')
            result.update(status='ready' if enabled else 'disabled', reason=None)
        else:
            result.update(status='ready', reason=None)
    except Denied as error:
        result['reason'] = str(error)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result['reason'] = 'invalid_ci_evidence'
    (root / 'gate.json').write_text(json.dumps(result) + '\n')
    if result['status'] == 'blocked':
        print('::error title=Gaon deployment blocked::' + result['reason'])
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(admit(sys.argv[1], latest_only='--latest-only' in sys.argv[2:]))
