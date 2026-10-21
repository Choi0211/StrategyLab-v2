"""GitHub-side report assembly. Only sanitized deployment JSON is published."""
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone


def assemble(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    try:
        ci = json.loads((root / 'ci.json').read_text())
        if not isinstance(ci, dict):
            raise ValueError('invalid CI report')
    except (OSError, ValueError):
        ci = {'status': 'unavailable'}
    remote = {'status': 'not_started'}
    if (root / 'remote.json').exists():
        try:
            remote = json.loads((root / 'remote.json').read_text())
            if not isinstance(remote, dict):
                raise ValueError('invalid report')
        except (ValueError, OSError):
            remote = {'status': 'unknown', 'error': 'remote_report_unavailable'}
    prs = json.loads(os.environ.get('PR_NUMBERS', '[]'))
    target = os.environ['GITHUB_SHA']
    transport_ok = (root / 'transport-exit.txt').exists() and (root / 'transport-exit.txt').read_text().strip() == '0'
    # An SSH failure/partial output must never become success via a stale report.
    if remote.get('status') == 'success' and (not transport_ok or remote.get('target_sha') != target or remote.get('run_id') != os.environ['DEPLOY_RUN_ID']):
        remote = {'status': 'unknown', 'error': 'remote_report_identity_mismatch'}
    report = {'started_at': None, 'finished_at': None, 'services': {}, 'api_healthy': False,
              'db_schema_version': None, 'running_sha': None, 'previous_sha': None,
              'rollback_attempted': False, 'rollback_succeeded': False,
              **remote, 'report_schema_version': 1, 'target_sha': target,
              'pr_number': prs[0] if len(prs) == 1 else None, 'pr_numbers': prs,
              'ci': ci, 'deployment_enabled': os.environ.get('DEPLOY_ENABLED') == 'true',
              'reported_at': datetime.now(timezone.utc).isoformat(),
              'workflow_run_url': f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
              'environment': 'gaon-production', 'db_restored': False}
    if ci.get('status') != 'passed' or ci.get('sha') != target:
        report['status'] = 'blocked_ci'
    elif not report['deployment_enabled']:
        report['status'] = 'disabled'
    (root / 'deployment.json').write_text(json.dumps(report, indent=2) + '\n')
    summary = '\n'.join(['## Gaon production deployment', '',
        f"- Status: `{report['status']}`", f"- SHA: `{target}`",
        f"- PRs: `{prs}`", f"- CI: `{ci.get('status')}`",
        f"- Finished: `{report.get('finished_at', report['reported_at'])}`",
        f"- Running SHA: `{report.get('running_sha')}`",
        f"- Services: `{json.dumps(report.get('services', {}), sort_keys=True)}`",
        f"- API healthy: `{report.get('api_healthy', False)}`",
        f"- DB schema: `{report.get('db_schema_version')}`",
        f"- Rollback: `{report.get('rollback_succeeded', False)}`",
        '- Database restored: **false**', '',
        'Download the `gaon-deployment-<run>-<attempt>` artifact for deployment.json and ci.json.',
        'A disabled, waiting, failed or unknown run is not a successful deployment.', ''])
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write(summary)
    return report


if __name__ == '__main__':
    assemble(sys.argv[1])
