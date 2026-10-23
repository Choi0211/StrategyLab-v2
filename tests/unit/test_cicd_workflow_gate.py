"""Runner admission regressions; no network, SSH or production mutations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_cicd_production import module

gate = module('gaon_workflow_admission', 'deploy/cicd/workflow_gate.py')
reporter = module('gaon_workflow_admission_report', 'deploy/cicd/report.py')
TARGET, OLD = 'b' * 40, 'a' * 40


class WorkflowAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = {'GITHUB_SHA': TARGET, 'GITHUB_REPOSITORY': 'Choi0211/StrategyLab-v2',
                    'GITHUB_RUN_ID': '123', 'DEPLOY_RUN_ID': '123-1', 'DEPLOY_ENABLED': 'true',
                    'GITHUB_ENV': str(self.root / 'env'), 'GITHUB_OUTPUT': str(self.root / 'output')}
        environment = patch.dict(os.environ, self.env)
        environment.start()
        self.addCleanup(environment.stop)
        self.ci = {'status': 'passed', 'sha': TARGET, 'source_dirty': False,
                   'suites': {name: {'passed': True, 'executed': 10, 'failures': 0, 'errors': 0}
                              for name in ('unit', 'integration')}}
        self.write_ci()
        self.records = [{'number': 260, 'mergeCommit': {'oid': TARGET}}]

    def write_ci(self):
        (self.root / 'ci.json').write_text(json.dumps(self.ci))

    def run_gate(self, sha=TARGET, records=None, **kwargs):
        with patch.object(gate, 'github', side_effect=[{'object': {'sha': sha}},
                                                       self.records if records is None else records]):
            return gate.admit(self.root, **kwargs)

    def test_current_main_exact_clean_nonempty_ci_and_merged_pr_admitted(self):
        self.assertEqual(self.run_gate(), 0)
        self.assertEqual((self.root / 'output').read_text(), 'ready=true\n')
        self.assertIn('DEPLOY_PRS=260\n', (self.root / 'env').read_text())

    def test_approved_obsolete_run_never_reaches_transport(self):
        self.assertEqual(self.run_gate(sha=OLD), 1)
        self.assertFalse((self.root / 'output').exists())
        report = reporter.assemble(self.root)
        self.assertEqual(report['status'], 'blocked_gate')
        self.assertEqual(report['gate']['reason'], 'superseded_main')
        self.assertFalse(report['api_healthy'])

    def test_main_advance_after_gate_is_denied_at_second_check(self):
        self.assertEqual(self.run_gate(), 0)
        self.assertEqual(self.run_gate(sha=OLD, latest_only=True), 1)
        self.assertEqual(reporter.assemble(self.root)['status'], 'blocked_gate')

    def test_disabled_configuration_cannot_emit_ready_true(self):
        with patch.dict(os.environ, {'DEPLOY_ENABLED': 'false'}):
            self.assertEqual(self.run_gate(), 0)
        self.assertEqual((self.root / 'output').read_text(), 'ready=false\n')

    def test_unmerged_or_missing_pr_is_denied(self):
        for records in ([], [{'number': 259, 'mergeCommit': {'oid': OLD}}]):
            with self.subTest(records=records):
                self.assertEqual(self.run_gate(records=records), 1)
                self.assertFalse((self.root / 'output').exists())

    def test_dirty_wrong_sha_failed_empty_and_incomplete_ci_are_denied(self):
        mutations = [{'source_dirty': True}, {'sha': OLD}, {'status': 'failed'},
                     {'suites': {}}, {'suites': {'unit': {'passed': True, 'executed': 1}}},
                     {'suites': {name: {'passed': True, 'executed': 0} for name in ('unit', 'integration')}},
                     {'suites': {name: {'passed': True, 'executed': 10, 'errors': 1} for name in ('unit', 'integration')}}]
        original = self.ci.copy()
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.ci = {**original, **mutation}
                self.write_ci()
                self.assertEqual(self.run_gate(), 1)
                self.assertFalse((self.root / 'output').exists())

    def test_cli_failure_timeout_and_malformed_response_are_sanitized(self):
        for error in (subprocess.CalledProcessError(1, 'gh', stderr='SECRET'),
                      subprocess.TimeoutExpired('gh SECRET', 30), OSError('SECRET')):
            with patch.object(gate.subprocess, 'run', side_effect=error):
                self.assertEqual(gate.admit(self.root), 1)
            text = (self.root / 'gate.json').read_text()
            self.assertNotIn('SECRET', text)
            self.assertIn('github_authorization_unavailable', text)

    def test_workflow_never_cancels_active_deployment_or_owns_global_slot(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/gaon-production.yml').read_text()
        self.assertNotIn('cancel-in-progress:', workflow)
        self.assertNotIn('concurrency:', workflow)
        self.assertIn('name: gaon-production', workflow)
        self.assertIn('workflow_gate.py report --latest-only', workflow)
        self.assertIn('report/gate.json', workflow)
