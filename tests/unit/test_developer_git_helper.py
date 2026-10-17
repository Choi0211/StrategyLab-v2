from __future__ import annotations
import unittest
from unittest.mock import patch
from pathlib import Path
import gaon.runtime.developer_git_helper as helper

class DeveloperGitHelperTests(unittest.TestCase):
    def test_invalid_task_and_unknown_action_fail_closed(self):
        with self.assertRaises(ValueError): helper._task('../escape')
        with self.assertRaises(PermissionError): helper.handle_request({'action':'merge','task_id':'safe-task'})

    def test_push_is_bound_to_verified_gaon_dev_branch(self):
        path=Path('/tmp/fake-worktree')
        with patch.object(helper,'_worktree',return_value=path), patch.object(helper,'_verify_repo',return_value='gaon-dev/safe-task'), patch.object(helper,'_push',return_value={'ok':True,'action':'push','branch':'gaon-dev/safe-task','output':'ok'}):
            result=helper.handle_request({'action':'push','task_id':'safe-task'})
        self.assertTrue(result['ok'])
        self.assertFalse(result['main_merged'])
        self.assertFalse(result['deployed'])
        self.assertFalse(result['trading_executed'])

if __name__ == '__main__': unittest.main()
