"""Permission-boundary tests. No server, SSH, sudo or systemd operations."""
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from test_cicd_production import module

supervisor = module('gaon_permission_supervisor', 'deploy/cicd/deployment_broker.py')
ingress = module('gaon_permission_ingress', 'deploy/cicd/ssh_deploy.py')
worker_module = module('gaon_permission_worker', 'deploy/cicd/deploy_worker.py')
service_module = module('gaon_permission_service', 'deploy/cicd/service_control.py')
OLD, TARGET, RUN, PRS = 'a' * 40, 'b' * 40, '123-1', '257'


class DeploymentPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        (self.state / 'reports').mkdir()
        self.state_patch = patch.object(supervisor, 'STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        if os.name != 'posix':
            # The broker refuses native Windows. Model Unix directory fsync
            # while exercising the RPC/checkpoint logic on Windows CI too.
            directory_sync = patch.object(supervisor, 'fsync_directory')
            directory_sync.start()
            self.addCleanup(directory_sync.stop)
        self.credentials = {'user': 995, 'group': 995, 'extra_groups': [], 'umask': 0o077}
        self.services = {unit: {'state': 'active', 'pid': 10 + i, 'code_directory_matches': True}
                         for i, unit in enumerate(('strategylab-gaon.service', 'gaon-web.service'))}
        self.control = SimpleNamespace(OPERATIONS={name: None for name in
            ('stop-web', 'stop-runtime', 'start-web', 'start-runtime')}, dispatch=Mock(side_effect=self.dispatch), health=Mock(return_value=True))
        self.session = supervisor.Session(self.control, self.credentials, TARGET, RUN, PRS)

    def dispatch(self, args):
        if args == ['inspect']:
            return {'schema_version': 48, 'integrity': 'ok'}
        if args[0] == 'status':
            return {'services': self.services, 'recent_error_count': 0}
        return {'ok': True}

    def request(self, operation, *args):
        return self.session.request({'operation': operation, 'args': list(args)})

    def prepare(self):
        with patch.object(supervisor, 'head', return_value=OLD), patch.object(supervisor, 'authorize'):
            self.request('prepare', OLD, '48')

    def test_ingress_has_only_fixed_broker_command_and_clean_environment(self):
        with patch.dict(os.environ, {'SSH_ORIGINAL_COMMAND': f'deploy {TARGET} {RUN} {PRS}',
                                     'LD_PRELOAD': 'attacker', 'GIT_DIR': '/tmp/attacker'}), patch.object(
            ingress.sys, 'stdin', SimpleNamespace(buffer=BytesIO(b'# v2 git bundle\n' + TARGET.encode() + b' HEAD\n\nPACK'))
        ), patch.object(ingress.subprocess, 'call', return_value=0) as call:
            self.assertEqual(ingress.main(), 0)
        args, kwargs = call.call_args
        self.assertEqual(args[0], ['/usr/bin/sudo', '-n', '/usr/local/sbin/gaon-deployment-broker',
                                  'deploy', TARGET, RUN, PRS])
        self.assertEqual(kwargs['env'], {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        for original in ('bash', 'deploy ../x 123-1 257', f'deploy {TARGET} {RUN} {PRS};id',
                         f'deploy {TARGET} {RUN} {PRS} /arbitrary/path'):
            with patch.dict(os.environ, {'SSH_ORIGINAL_COMMAND': original}), patch.object(ingress.subprocess, 'call') as call:
                self.assertEqual(ingress.main(), 2)
                call.assert_not_called()

    def test_ingress_rejects_missing_mismatched_or_oversized_bundle_before_sudo(self):
        for data in (b'not a bundle', b'# v2 git bundle\n' + OLD.encode() + b' HEAD\n\nPACK',
                     b'# v2 git bundle\n\nPACK'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                ingress.receive(BytesIO(data), BytesIO(), TARGET)
        with patch.object(ingress, 'MAX_BUNDLE', 2), self.assertRaises(ValueError):
            ingress.receive(BytesIO(b'oversized'), BytesIO(), TARGET)

    def test_disconnect_is_deferred_until_rpc_response_is_consumed(self):
        events = []
        signals = SimpleNamespace(SIG_BLOCK=0, SIG_SETMASK=1, SIGTERM=15, SIGHUP=1,
                                  pthread_sigmask=Mock(side_effect=lambda mode, mask: events.append(mode) or set()))
        channel = Mock()
        channel.write.side_effect = lambda _: events.append('write')
        channel.readline.side_effect = lambda _: events.append('read') or b'{"ok":true,"result":{"ok":true}}\n'
        with patch.object(worker_module, 'signal', signals):
            result = worker_module.Controller(channel).call('stop-web')
        self.assertTrue(result['ok'])
        self.assertEqual(events, [0, 'write', 'read', 1])

    def test_enable_marker_is_verified_only_by_privileged_broker(self):
        # The worker runs as strategylab; /etc/gaon-deploy is root-only.
        # Rechecking its marker in the worker raises PermissionError before
        # a backup can be taken, despite the broker having admitted the run.
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        broker = (root / 'deploy/cicd/deployment_broker.py').read_text()
        worker = (root / 'deploy/cicd/deploy_worker.py').read_text()
        self.assertIn("ENABLED.read_text().strip() != 'enabled'", broker)
        self.assertNotIn('self.p.enabled.is_file()', worker)
        self.assertNotIn('self.p.enabled.read_text()', worker)

    def test_root_metadata_denies_commands_units_paths_duplicate_prs(self):
        self.assertEqual(supervisor.metadata(['deploy', TARGET, RUN, PRS]), [TARGET, RUN, PRS])
        for args in (['bash'], ['restart', 'binance-trading-live.service'],
                     ['deploy', TARGET, RUN, '/etc/shadow'], ['deploy', TARGET, RUN, '257,257'],
                     ['deploy', TARGET, '../outside', PRS], ['deploy', TARGET, RUN, PRS, '/tmp/bundle']):
            with self.subTest(args=args), self.assertRaises(ValueError):
                supervisor.metadata(args)

    def test_independent_github_authorization_binds_current_main_and_merged_pr(self):
        workflow = {'id': 123, 'run_attempt': 1, 'head_sha': TARGET, 'head_branch': 'main',
                    'path': '.github/workflows/gaon-production.yml', 'event': 'push', 'status': 'in_progress'}
        jobs = {'jobs': [{'name': 'Verify exact production SHA', 'head_sha': TARGET, 'conclusion': 'success'},
                         {'name': 'Approved Gaon deployment (disabled until configured)',
                          'head_sha': TARGET, 'status': 'in_progress'}]}
        approved = {'number': 257, 'merged_at': '2026-10-22T00:00:00Z', 'merge_commit_sha': TARGET,
                    'base': {'ref': 'main', 'repo': {'full_name': 'Choi0211/StrategyLab-v2'}}}
        with patch.object(supervisor, 'github_json', side_effect=[workflow, jobs, {'object': {'sha': TARGET}}, [approved]]):
            supervisor.authorize(TARGET, PRS, RUN)
        for record in ({**approved, 'merged_at': None}, {**approved, 'merge_commit_sha': OLD},
                       {**approved, 'number': 258}, {**approved, 'base': {'ref': 'other'}}):
            with patch.object(supervisor, 'github_json', side_effect=[workflow, jobs, {'object': {'sha': TARGET}}, [record]]), self.assertRaises(ValueError):
                supervisor.authorize(TARGET, PRS, RUN)
        with patch.object(supervisor, 'github_json', side_effect=[workflow, jobs, {'object': {'sha': OLD}}]), self.assertRaises(ValueError):
            supervisor.authorize(TARGET, PRS, RUN)
        with patch.object(supervisor, 'github_json', side_effect=OSError('offline')), self.assertRaises(OSError):
            supervisor.authorize(TARGET, PRS, RUN)
        for bad in ({**workflow, 'head_sha': OLD}, {**workflow, 'status': 'completed'},
                    {**workflow, 'run_attempt': 2}, {**workflow, 'path': 'attacker.yml'}):
            with patch.object(supervisor, 'github_json', return_value=bad), self.assertRaises(ValueError):
                supervisor.authorize(TARGET, PRS, RUN)
        for status in ('queued', 'waiting', 'completed'):
            bad_jobs = {'jobs': [jobs['jobs'][0], {**jobs['jobs'][1], 'status': status}]}
            with patch.object(supervisor, 'github_json', side_effect=[workflow, bad_jobs]), self.assertRaises(ValueError):
                supervisor.authorize(TARGET, PRS, RUN)

    def test_checkpoint_precedes_partial_stop_and_is_bound_to_actual_head(self):
        with self.assertRaises(ValueError):
            self.request('prepare', TARGET, '48')
        self.control.dispatch.assert_not_called()
        with patch.object(supervisor, 'head', return_value=TARGET), self.assertRaises(ValueError):
            self.request('prepare', OLD, '48')
        self.assertFalse(self.session.journal.exists())
        self.prepare()
        self.assertEqual(json.loads(self.session.journal.read_text())['previous_sha'], OLD)
        def stop(args):
            self.assertTrue(json.loads(self.session.journal.read_text())['stopped'])
            raise RuntimeError('partial stop')
        self.control.dispatch.side_effect = stop
        with self.assertRaises(RuntimeError):
            self.request('stop-web')
        self.assertTrue(self.session.stopped)

    def test_checkpoint_fsync_failure_never_enables_service_mutation(self):
        with patch.object(supervisor, 'head', return_value=OLD), patch.object(supervisor, 'authorize'), patch.object(
            supervisor, 'save', side_effect=OSError('disk full')
        ), self.assertRaises(OSError):
            self.request('prepare', OLD, '48')
        self.assertIsNone(self.session.previous)
        self.control.dispatch.reset_mock()
        for operation in ('stop-web', 'start-runtime'):
            with self.assertRaises(ValueError):
                self.request(operation)
        self.control.dispatch.assert_not_called()
        self.assertFalse(self.session.stopped)

    def test_rpc_denies_arbitrary_commands_units_paths_and_unprepared_start(self):
        for operation, args in (('start-web', []), ('systemctl', ['restart', 'MyMoneyGuard.service']),
                                ('restore', []), ('backup', ['../elsewhere']), ('inspect', ['/etc/shadow']),
                                ('prepare', [OLD, '48', 'extra'])):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                self.request(operation, *args)
        self.control.dispatch.assert_not_called()
        self.prepare()
        for operation in self.control.OPERATIONS:
            self.request(operation)
        for args in (['start-web', 'other.service'], ['stop-web', '/etc/shadow']):
            with self.assertRaises(ValueError):
                self.request(*args)

    def test_git_permission_denial_aborts_before_privileged_service_mutations(self):
        with patch.object(supervisor, 'head', side_effect=PermissionError('Git write denied')), self.assertRaises(PermissionError):
            self.request('prepare', OLD, '48')
        self.control.dispatch.assert_not_called()
        self.assertFalse(self.session.stopped)

    def test_worker_is_always_fixed_root_installed_script_with_dropped_identity(self):
        parent, child = MagicMock(), Mock()
        child.fileno.return_value = 31
        process = Mock(returncode=0)
        process.poll.return_value = 0
        process.stdout.read.return_value = b'{"status":"failed"}'
        signals = SimpleNamespace(SIGTERM=15, SIGHUP=1, signal=Mock())
        with patch.object(supervisor.socket, 'socketpair', return_value=(parent, child)), patch.object(
            supervisor.subprocess, 'Popen', return_value=process
        ) as popen, patch.object(supervisor, 'signal', signals):
            self.session.worker('deploy', TARGET, BytesIO(b'bundle'))
        args, kwargs = popen.call_args
        self.assertEqual(supervisor.WORKER.as_posix(), '/usr/local/libexec/gaon-deploy-worker.py')
        self.assertEqual(args[0], ['/usr/bin/python3', '-I', str(supervisor.WORKER),
                                  'deploy', TARGET, RUN, PRS, '31'])
        for name, value in self.credentials.items():
            self.assertEqual(kwargs[name], value)
        self.assertEqual(kwargs['pass_fds'], (31,))
        self.assertTrue(kwargs['start_new_session'])
        self.assertNotIn('shell', kwargs)
        self.assertEqual(kwargs['cwd'], '/')
        handler = signals.signal.call_args_list[0].args[1]
        handler()
        handler()
        process.send_signal.assert_called_once_with(15)

    def test_real_private_socket_protocol_flushes_reply_before_worker_continues(self):
        parent, child = supervisor.socket.socketpair()
        peer = child.dup()
        peer.settimeout(2)
        complete, replies, errors = threading.Event(), [], []
        def communicate():
            try:
                with peer, peer.makefile('rwb') as channel:
                    channel.write(b'{"operation":"health","args":[]}\n')
                    channel.flush()
                    replies.append(json.loads(channel.readline()))
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                complete.set()
        thread = threading.Thread(target=communicate)
        process = Mock(returncode=0)
        process.poll.side_effect = lambda: 0 if complete.is_set() else None
        process.stdout = BytesIO(b'{"status":"failed"}')
        process.wait.side_effect = lambda timeout: thread.join(timeout)
        def spawn(*_args, **_kwargs):
            thread.start()
            return process
        signals = SimpleNamespace(SIGTERM=15, SIGHUP=1, signal=Mock())
        with patch.object(supervisor.socket, 'socketpair', return_value=(parent, child)), patch.object(
            supervisor.subprocess, 'Popen', side_effect=spawn
        ), patch.object(supervisor, 'signal', signals):
            self.session.worker('deploy', TARGET, BytesIO(b'bundle'))
        self.assertEqual(errors, [])
        self.assertEqual(replies, [{'ok': True, 'result': {'healthy': True}}])

    def test_interrupted_worker_triggers_fixed_old_sha_recovery_without_db_restore(self):
        self.prepare()
        self.session.stopped = True
        with patch.object(self.session, 'worker', side_effect=[InterruptedError(),
            {'status': 'failed', 'rollback_succeeded': True}]) as worker, patch.object(self.session, 'observe', return_value={}):
            result = self.session.execute(BytesIO(b'bundle'))
        self.assertTrue(result['rollback_succeeded'])
        self.assertFalse(result['db_restored'])
        self.assertEqual(worker.call_args_list[1].args[:2], ('recover', OLD))
        self.assertFalse(self.session.journal.exists())

    def test_failed_recovery_leaves_journal_and_only_two_services_stopped(self):
        self.prepare()
        self.session.stopped = True
        self.control.dispatch.reset_mock()
        with patch.object(self.session, 'worker', side_effect=RuntimeError('worker died')):
            result = self.session.execute(BytesIO(b'bundle'))
        self.assertTrue(result['manual_recovery_required'])
        self.assertTrue(self.session.journal.exists())
        mutations = [call.args[0] for call in self.control.dispatch.call_args_list if call.args[0][0].startswith(('stop-', 'start-'))]
        self.assertEqual(mutations, [['stop-web'], ['stop-runtime']])

    def test_false_success_without_checkpoint_is_not_published_as_success(self):
        with patch.object(self.session, 'worker', return_value={'status': 'success'}):
            result = self.session.execute(BytesIO(b'bundle'))
        self.assertEqual(result['status'], 'unknown')

    def test_success_requires_root_observed_head_schema_fresh_pids_and_health(self):
        self.prepare()
        self.session.stopped = True
        self.session.before = {unit: {**item, 'pid': 1} for unit, item in self.services.items()}
        with patch.object(self.session, 'worker', return_value={'status': 'success'}), patch.object(
            supervisor, 'head', return_value=TARGET
        ):
            result = self.session.execute(BytesIO(b'bundle'))
        self.assertEqual(result['status'], 'success')
        self.control.health.assert_called_once_with()
        self.assertEqual(result['db_schema_version'], 48)

    def test_health_is_fixed_loopback_without_redirect_or_secret_output(self):
        for status, body, expected in ((200, b'{"status":"ok"}', True), (302, b'', False),
                                       (200, b'[]', False), (500, b'secret fixture', False)):
            connection = Mock()
            connection.getresponse.return_value.status = status
            connection.getresponse.return_value.read.return_value = body
            with patch.object(service_module.http.client, 'HTTPConnection', return_value=connection) as factory:
                self.assertEqual(service_module.health(), expected)
            factory.assert_called_once_with('127.0.0.1', 8765, timeout=5)
            connection.request.assert_called_once_with('GET', '/gaon/health')
            connection.close.assert_called_once_with()

    def test_untrusted_helper_ownership_symlink_or_writable_mode_rejected(self):
        for uid, mode in ((995, stat_mode(0o644)), (0, stat_mode(0o666)), (0, 0o120777)):
            path = Mock(parents=())
            path.lstat.return_value = SimpleNamespace(st_uid=uid, st_mode=mode)
            with self.assertRaises(ValueError):
                supervisor.trusted(path)

    def test_real_read_only_git_directory_rejects_ingress_write(self):
        if os.name != 'posix':
            self.assertEqual(supervisor.main(), 2)  # Explicit unsupported-platform refusal.
            return
        code = self.state / 'read-only-code'
        code.mkdir()
        subprocess.run(['git', 'init', '-q', str(code)], check=True)
        directory = code / '.git/refs/heads'
        directory.chmod(0o555)
        self.state.chmod(0o755)
        try:
            credentials = {'user': 65534, 'group': 65534, 'extra_groups': []} if os.geteuid() == 0 else {}
            result = subprocess.run(['git', '-c', 'safe.directory=' + str(code), '-C', str(code),
                                     'symbolic-ref', 'refs/heads/probe', 'refs/heads/main'],
                                    capture_output=True, **credentials)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((directory / 'probe').exists())
        finally:
            directory.chmod(0o755)
            self.state.chmod(0o700)

    def test_second_supervisor_cannot_take_the_same_deployment_lock(self):
        if supervisor.fcntl is None:
            self.assertEqual(supervisor.main(), 2)
            return
        with (self.state / 'deploy.lock').open('a') as first, (self.state / 'deploy.lock').open('a') as second:
            supervisor.fcntl.flock(first, supervisor.fcntl.LOCK_EX | supervisor.fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                supervisor.fcntl.flock(second, supervisor.fcntl.LOCK_EX | supervisor.fcntl.LOCK_NB)
            with self.assertRaises(supervisor.DeploymentBusy):
                supervisor.acquire(second, timeout=0)

    def test_short_lock_contention_retries_without_cancelling_first_deployment(self):
        locks = SimpleNamespace(LOCK_EX=2, LOCK_NB=4,
                                flock=Mock(side_effect=[BlockingIOError(), None]))
        with patch.object(supervisor, 'fcntl', locks), patch.object(supervisor.time, 'sleep') as sleep:
            supervisor.acquire(99)
        self.assertEqual(locks.flock.call_count, 2)
        sleep.assert_called_once()

    def test_contended_lock_has_bounded_deadline_on_all_test_platforms(self):
        locks = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=Mock(side_effect=BlockingIOError()))
        with patch.object(supervisor, 'fcntl', locks), patch.object(supervisor.time, 'sleep') as sleep, patch.object(
                supervisor.time, 'monotonic', side_effect=[0, 119, 120]):
            with self.assertRaises(supervisor.DeploymentBusy):
                supervisor.acquire(99)
        sleep.assert_called_once_with(1)


def stat_mode(mode):
    return 0o100000 | mode
