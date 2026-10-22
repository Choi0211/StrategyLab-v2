from __future__ import annotations
import unittest
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
import gaon.runtime.developer_git_helper as helper

class DeveloperGitHelperTests(unittest.TestCase):
    def test_invalid_task_and_unknown_action_fail_closed(self):
        with self.assertRaises(ValueError): helper._task('../escape')
        with self.assertRaises(PermissionError): helper.handle_request({'action':'merge','task_id':'safe-task'})

    def test_push_is_bound_to_verified_gaon_dev_branch(self):
        path=Path('/tmp/fake-worktree')
        with patch.object(helper,'_require_unix_permissions') as permissions, patch.object(helper,'_worktree',return_value=path), patch.object(helper,'_verify_repo',return_value='gaon-dev/safe-task'), patch.object(helper,'_push',return_value={'ok':True,'action':'push','branch':'gaon-dev/safe-task','output':'ok'}):
            result=helper.handle_request({'action':'push','task_id':'safe-task'})
        permissions.assert_called_once_with()
        self.assertTrue(result['ok'])
        self.assertFalse(result['main_merged'])
        self.assertFalse(result['deployed'])
        self.assertFalse(result['trading_executed'])

    def test_import_without_grp_and_operations_fail_before_side_effects(self):
        # A fresh interpreter models Windows' missing module even on Linux.
        script = '''
import builtins
original = builtins.__import__
def without_grp(name, *args, **kwargs):
    if name == "grp":
        raise ModuleNotFoundError("No module named 'grp'")
    return original(name, *args, **kwargs)
builtins.__import__ = without_grp
import gaon.runtime.developer_git_helper as helper
assert helper.grp is None
from unittest.mock import patch
from pathlib import Path
with patch.object(Path, "mkdir") as mkdir, patch.object(helper.socket, "socket") as socket, patch.object(helper.subprocess, "run") as run, patch.object(helper, "_worktree") as worktree:
    for operation in (lambda: helper.serve(Path("must-not-be-created/socket")), lambda: helper.handle_request({"action": "push", "task_id": "safe-task"}), lambda: helper._run(["git", "status"], cwd=Path("."))):
        try:
            operation()
        except RuntimeError as exc:
            assert "requires Unix group ownership" in str(exc)
        else:
            raise AssertionError("unsupported operation was allowed")
    mkdir.assert_not_called()
    socket.assert_not_called()
    run.assert_not_called()
    worktree.assert_not_called()
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_windows_rejected_even_if_grp_and_chown_are_available(self):
        with patch.object(helper.sys, "platform", "win32"), patch.object(helper, "grp", Mock()), patch.object(
            helper.os, "chown", create=True
        ), patch.object(helper, "_worktree") as worktree:
            for action in ("push", "create_pr"):
                with self.subTest(action=action), self.assertRaisesRegex(RuntimeError, "unsupported on this platform"):
                    helper.handle_request({"action": action, "task_id": "safe-task"})
            worktree.assert_not_called()

    def test_unix_server_keeps_group_ownership_and_private_socket_mode(self):
        path = Mock()
        path.exists.return_value = False
        path.is_symlink.return_value = False
        group = Mock()
        group.getgrnam.return_value.gr_gid = 1234
        with patch.object(helper.sys, "platform", "linux"), patch.object(helper, "grp", group), patch.object(
            helper.os, "chown", create=True
        ) as chown, patch.object(helper.os, "chmod") as chmod, patch.object(
            helper.socket, "AF_UNIX", 1, create=True
        ), patch.object(helper.socket, "socket") as socket:
            server = socket.return_value.__enter__.return_value
            server.accept.side_effect = RuntimeError("stop test server")
            with self.assertRaisesRegex(RuntimeError, "stop test server"):
                helper.serve(path)
            group.getgrnam.assert_called_once_with("strategylab")
            chown.assert_called_once_with(path, 0, 1234)
            chmod.assert_called_once_with(path, 0o660)
            server.listen.assert_called_once_with(8)

    def test_missing_unix_socket_support_refuses_before_filesystem_changes(self):
        path = Mock()
        socket = Mock()
        with patch.object(helper.sys, "platform", "linux"), patch.object(helper, "grp", Mock()), patch.object(
            helper.os, "chown", create=True
        ), patch.object(helper, "socket", SimpleNamespace(socket=socket)):
            with self.assertRaisesRegex(RuntimeError, "requires Unix group ownership and socket permissions"):
                helper.serve(path)
        path.parent.mkdir.assert_not_called()
        path.unlink.assert_not_called()
        socket.assert_not_called()

if __name__ == '__main__': unittest.main()
