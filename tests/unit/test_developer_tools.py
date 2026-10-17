from __future__ import annotations
import unittest
from gaon.runtime.developer_tools import _task_id,_patch_paths,repository_read

class DeveloperToolBoundaryTests(unittest.TestCase):
    def test_task_id_is_bounded(self):
        self.assertEqual(_task_id("Fix-123"),"fix-123")
        with self.assertRaises(ValueError): _task_id("../escape")

    def test_patch_paths_allow_source_and_deny_sensitive(self):
        patch="--- a/src/gaon/x.py\n+++ b/src/gaon/x.py\n@@ -1 +1 @@\n-a\n+b\n"
        self.assertEqual(_patch_paths(patch),("src/gaon/x.py",))
        bad="--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-a\n+b\n"
        with self.assertRaises(PermissionError): _patch_paths(bad)

    def test_repository_reader_denies_env(self):
        with self.assertRaises(PermissionError): repository_read({"path":".env"})

if __name__ == "__main__": unittest.main()
