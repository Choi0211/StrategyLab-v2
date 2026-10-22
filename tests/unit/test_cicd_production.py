"""Real local Git/SQLite deployment simulations; never SSH/systemd/production."""
import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


deploy = module('gaon_cicd_deploy', 'deploy/cicd/ssh_deploy.py')
broker = module('gaon_cicd_broker', 'deploy/cicd/service_control.py')
reporter = module('gaon_cicd_report', 'deploy/cicd/report.py')
verifier = module('gaon_cicd_verify', 'scripts/verify_release.py')


class LocalControl:
    def __init__(self, test):
        self.test = test
        self.calls = []
        self.pids = {unit: 10 + i for i, unit in enumerate(deploy.UNITS)}
        self.counter = 20
        self.fail_operation = None
        self.fail_health = False
        self.errors = 0

    def call(self, operation, *args):
        self.calls.append(operation)
        if operation == self.fail_operation:
            self.fail_operation = None
            raise RuntimeError('synthetic failure containing a secret: never report this text')
        if operation == 'inspect':
            with sqlite3.connect(self.test.db) as db:
                return {'schema_version': db.execute('SELECT MAX(version) FROM schema_version').fetchone()[0], 'integrity': 'ok'}
        if operation == 'backup':
            copy = self.test.base / ('db-backup-' + args[0])
            with sqlite3.connect(self.test.db) as source, sqlite3.connect(copy) as target:
                source.backup(target)
            return {'backup': str(copy), 'backup_integrity': 'ok', **self.call('inspect')}
        if operation == 'status':
            return {'services': {u: {'state': 'active' if p else 'inactive', 'pid': p,
                    'code_directory_matches': True} for u, p in self.pids.items()},
                    'recent_error_count': self.errors if self.test.head() == self.test.target else 0}
        if operation.startswith(('stop-', 'start-')):
            unit = deploy.UNITS[0 if operation.endswith('runtime') else 1]
            self.counter += 1
            self.pids[unit] = self.counter if operation.startswith('start-') else 0
            if operation == 'start-runtime' and self.test.head() == self.test.target:
                with sqlite3.connect(self.test.db) as db:
                    db.execute("INSERT INTO observations VALUES ('written-after-backup')")
            return {'ok': True}
        raise AssertionError('forbidden operation: ' + operation)

    def health(self):
        return not (self.fail_health and self.test.head() == self.test.target)


class LocalDeployment(deploy.Deployment):
    def import_check(self):
        # Transport/system-service boundary only; Git and SQLite are real.
        if (self.p.code / 'bad-import').exists():
            raise ImportError('synthetic broken application')


@unittest.skipUnless(os.name == 'posix', 'Linux production deployment simulation')
class ProductionDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.code = self.base / 'code'
        self.code.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'CI test')
        self.git('config', 'user.email', 'ci-test@example.invalid')
        (self.code / 'src/gaon/runtime').mkdir(parents=True)
        (self.code / 'src/gaon/runtime/migrations.py').write_text('SCHEMA_VERSION = 48\n')
        (self.code / 'pyproject.toml').write_text('# unchanged dependencies\n')
        (self.code / 'application.py').write_text('version = 1\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'previous')
        self.previous = self.head()
        (self.code / 'application.py').write_text('version = 2\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'target')
        self.target = self.head()
        self.bundle = self.base / 'release.bundle'
        self.git('bundle', 'create', str(self.bundle), 'HEAD')
        self.git('switch', '--detach', self.previous)
        (self.code / 'deploy_backups').mkdir()
        (self.code / 'deploy_backups/keep').write_text('existing backup')
        self.enabled = self.base / 'enabled'
        self.enabled.write_text('enabled\n')
        self.db = self.base / 'runtime.sqlite'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE schema_version (version INTEGER)')
            db.execute('INSERT INTO schema_version VALUES (48)')
            db.execute('CREATE TABLE observations (value TEXT)')
        self.control = LocalControl(self)
        self.engine = LocalDeployment(deploy.Policy(self.code, self.base / 'state', self.enabled), self.control)
        self.sleep = patch.object(deploy.time, 'sleep')
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.code, text=True, stderr=subprocess.DEVNULL).strip()

    def head(self):
        return self.git('rev-parse', 'HEAD')

    def execute(self):
        return self.engine.execute(self.target, '123-1', '257', self.bundle)

    def test_success_exact_sha_backups_schema_and_preservation(self):
        result = self.execute()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(self.head(), self.target)
        self.assertEqual(result['running_sha'], self.target)
        self.assertEqual(result['db_schema_version'], 48)
        self.assertTrue(Path(result['code_backup']).is_file())
        self.assertTrue(Path(result['database_backup']['backup']).is_file())
        self.assertEqual((self.code / 'deploy_backups/keep').read_text(), 'existing backup')
        self.assertFalse(result['db_restored'])
        self.assertTrue(all(op in {'inspect', 'backup', 'status', *broker.OPERATIONS} for op in self.control.calls))

    def test_disabled_has_no_git_or_service_changes(self):
        self.enabled.unlink()
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.control.calls, [])
        self.assertEqual(self.head(), self.previous)

    def test_bad_sha_and_shell_injection_rejected(self):
        for value in ('main', self.target + ';id', '../main'):
            with self.assertRaises(ValueError):
                self.engine.execute(value, '123-1', '257', self.bundle)
        self.assertEqual(self.control.calls, [])

    def test_wrong_bundle_sha_never_stops_services(self):
        result = self.engine.execute('a' * 40, '123-1', '257', self.bundle)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('stop-web', self.control.calls)
        self.assertEqual(self.head(), self.previous)

    def test_dirty_checkout_never_stops_services(self):
        (self.code / 'application.py').write_text('local work')
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.control.calls, [])

    def test_schema_mismatch_is_blocked_before_stop(self):
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE schema_version SET version=49')
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('stop-web', self.control.calls)

    def test_dependency_migration_and_backup_path_edits_require_manual_rollout(self):
        for path, content in (('pyproject.toml', '# changed dependency\n'),
                              ('src/gaon/runtime/migrations.py', 'SCHEMA_VERSION = 49\n'),
                              ('deploy_backups/keep', 'must not overwrite\n')):
            with self.subTest(path=path):
                (self.code / path).write_text(content)
                self.git('add', path)
                self.git('commit', '-qm', 'disallowed auto rollout')
                self.target = self.head()
                bundle = self.base / ('bundle-' + self.target)
                self.git('bundle', 'create', str(bundle), 'HEAD')
                self.git('switch', '--detach', self.previous)
                self.control.calls.clear()
                result = self.engine.execute(self.target, '987-1', '257', bundle)
                self.assertEqual(result['status'], 'failed')
                self.assertNotIn('stop-web', self.control.calls)

    def test_import_failure_rolls_back_and_does_not_report_success(self):
        self.git('switch', '--detach', self.target)
        (self.code / 'bad-import').write_text('broken')
        self.git('add', 'bad-import')
        self.git('commit', '-qm', 'broken import')
        self.target = self.head()
        bundle = self.base / 'broken.bundle'
        self.git('bundle', 'create', str(bundle), 'HEAD')
        self.git('switch', '--detach', self.previous)
        result = self.engine.execute(self.target, '345-1', '257', bundle)
        self.assertTrue(result['rollback_succeeded'])
        self.assertEqual(self.head(), self.previous)
        self.assertEqual(result['status'], 'failed')

    def test_backup_failure_does_not_change_code_or_stop(self):
        self.control.fail_operation = 'backup'
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.head(), self.previous)
        self.assertNotIn('stop-web', self.control.calls)
        self.assertNotIn('secret', json.dumps(result))

    def test_partial_stop_and_start_failures_restore_old_code(self):
        for operation in ('stop-web', 'stop-runtime', 'start-runtime', 'start-web'):
            with self.subTest(operation=operation):
                self.control.fail_operation = operation
                result = self.engine.execute(self.target, str(200 + len(self.control.calls)) + '-1', '257', self.bundle)
                self.assertEqual(result['status'], 'failed')
                self.assertTrue(result['rollback_succeeded'])
                self.assertEqual(self.head(), self.previous)

    def test_health_failure_rolls_back_code_without_restoring_db(self):
        self.control.fail_health = True
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['rollback_succeeded'])
        self.assertEqual(result['running_sha'], self.previous)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT value FROM observations').fetchall(), [('written-after-backup',)])
        self.assertFalse(result['db_restored'])

    def test_recent_errors_fail_deployment_even_when_health_is_ok(self):
        self.control.errors = 1
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['rollback_succeeded'])

    def test_failed_rollback_health_leaves_services_stopped_for_manual_recovery(self):
        self.control.health = lambda: 'stop-web' not in self.control.calls
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['manual_recovery_required'])
        self.assertFalse(result['rollback_succeeded'])
        self.assertTrue(all(pid == 0 for pid in self.control.pids.values()))
        self.assertTrue(all(service['state'] == 'inactive' for service in result['services'].values()))

    def test_unexpected_db_schema_drift_never_restores_database(self):
        original = self.control.call
        def call(operation, *args):
            value = original(operation, *args)
            if operation == 'start-runtime' and self.head() == self.target:
                with sqlite3.connect(self.db) as db:
                    db.execute('UPDATE schema_version SET version=49')
            return value
        self.control.call = call
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['db_schema_version'], 49)
        self.assertFalse(result['db_restored'])
        self.assertTrue(result['manual_recovery_required'])
        self.assertTrue(all(pid == 0 for pid in self.control.pids.values()))


class PrivilegedBrokerTests(unittest.TestCase):
    def test_journal_reports_counts_without_raw_log_messages(self):
        def command(args):
            if args[0].endswith('systemctl'):
                return 'ActiveState=active\nMainPID=123\nActiveEnterTimestampMonotonic=1\n'
            return json.dumps({'PRIORITY': '3', 'MESSAGE': 'sensitive fixture must stay local'})
        with patch.object(broker, 'command', side_effect=command):
            result = broker.dispatch(['status', str(int(broker.time.time()))])
        self.assertEqual(result['recent_error_count'], 1)
        self.assertNotIn('sensitive fixture', json.dumps(result))
    def test_only_two_fixed_units_and_no_db_restore(self):
        for args in (['restart', 'binance-trading-live.service'], ['restore'], ['backup', '../evil'], ['start-web', 'extra']):
            with patch.object(broker, 'command') as command, self.assertRaises(ValueError):
                broker.dispatch(args)
            command.assert_not_called()
        for operation, (verb, unit) in broker.OPERATIONS.items():
            with patch.object(broker, 'command', return_value='') as command:
                self.assertTrue(broker.dispatch([operation])['ok'])
                command.assert_called_once_with(['/usr/bin/systemctl', verb, unit])
                self.assertIn(unit, ('gaon-web.service', 'strategylab-gaon.service'))

    @unittest.skipUnless(os.name == 'posix', 'Linux production SQLite backup')
    def test_sqlite_backup_integrity_and_existing_backup_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            db_path = Path(temporary) / 'source.sqlite'
            with sqlite3.connect(db_path) as db:
                db.execute('CREATE TABLE schema_version (version INTEGER)')
                db.execute('INSERT INTO schema_version VALUES (48)')
            with patch.object(broker, 'DB', db_path), patch.object(broker, 'BACKUPS', Path(temporary) / 'backups'):
                result = broker.dispatch(['backup', '123-1'])
                self.assertEqual(result['backup_integrity'], 'ok')
                with self.assertRaises(FileExistsError):
                    broker.dispatch(['backup', '123-1'])


class DeploymentReportTests(unittest.TestCase):
    def test_failed_test_names_are_public_annotations_without_traceback_data(self):
        stderr = ('FAIL: test_order (test_reports.ReportTests.test_order)\n'
                  'AssertionError: private fixture data\n'
                  'ERROR: test_import (test_reports.ReportTests.test_import)\n')
        output = StringIO()
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), redirect_stdout(output):
            verifier._annotate_test_failures('unit', stderr)
        self.assertEqual(output.getvalue().count('::error title=unit test failed::'), 2)
        self.assertIn('test_order', output.getvalue())
        self.assertIn('test_import', output.getvalue())
        self.assertNotIn('private fixture', output.getvalue())

    def test_ci_zero_tests_and_failed_suite_stop_the_runner(self):
        for count, exit_code in ((0, 0), (2, 2)):
            with self.subTest(count=count):
                report = {'suites': {}}
                response = SimpleNamespace(returncode=exit_code, stdout='',
                    stderr=f'Ran {count} tests in 0.1s\nFAILED (failures=1)')
                with patch.object(verifier.subprocess, 'run', return_value=response) as execute, redirect_stdout(StringIO()):
                    self.assertNotEqual(verifier._verify(report), 0)
                self.assertEqual(execute.call_count, 1)
                self.assertEqual(report['suites']['unit']['executed'], count)

    def test_failed_ci_always_saves_machine_readable_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'ci.json'
            with patch.object(verifier.subprocess, 'check_output', side_effect=['a' * 40, '']), \
                 patch.object(verifier, '_verify', return_value=2):
                self.assertEqual(verifier.main(path), 2)
            report = json.loads(path.read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertFalse(report['source_dirty'])
            self.assertIn('finished_at', report)

    def test_stale_remote_success_and_failed_ci_never_report_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'ci.json').write_text(json.dumps({'status': 'passed', 'sha': 'a' * 40}))
            (root / 'remote.json').write_text(json.dumps({'status': 'success', 'target_sha': 'b' * 40, 'run_id': '123-1'}))
            env = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'DEPLOY_RUN_ID': '123-1',
                   'GITHUB_REPOSITORY': 'Choi0211/StrategyLab-v2', 'DEPLOY_ENABLED': 'true', 'PR_NUMBERS': '[257]'}
            with patch.dict(os.environ, env):
                result = reporter.assemble(root)
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['pr_number'], 257)
                self.assertFalse(result['db_restored'])
                (root / 'remote.json').write_text(json.dumps({'status': 'success', 'target_sha': 'a' * 40, 'run_id': '123-1'}))
                (root / 'transport-exit.txt').write_text('255')
                self.assertEqual(reporter.assemble(root)['status'], 'unknown')
                (root / 'transport-exit.txt').write_text('0')
                self.assertEqual(reporter.assemble(root)['status'], 'success')
                (root / 'ci.json').write_text(json.dumps({'status': 'failed', 'sha': 'a' * 40}))
                self.assertEqual(reporter.assemble(root)['status'], 'blocked_ci')
                with patch.dict(os.environ, {'DEPLOY_ENABLED': 'false'}):
                    (root / 'ci.json').write_text(json.dumps({'status': 'passed', 'sha': 'a' * 40}))
                    self.assertEqual(reporter.assemble(root)['status'], 'disabled')
