import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest

module_path=Path(__file__).resolve().parents[2]/"scripts/gaon_backup_permission_guard.py"
spec=importlib.util.spec_from_file_location("backup_permission_guard", module_path)
guard=importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

class BackupGuardTests(unittest.TestCase):
    def test_dry_run_and_enforced_permissions_preserve_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            sub=root/"pre-deploy"
            sub.mkdir()
            db=sub/"gaon-runtime.sqlite"
            db.write_bytes(b"SECRET_DB_CONTENT")
            db.chmod(0o644)
            env=root/"gaon-web.env.before-upgrade"
            env.write_text("SECRET_TEST_DUMMY=1")
            env.chmod(0o644)
            normal=root/"report.txt"
            normal.write_text("leave unchanged")
            normal.chmod(0o644)
            dry=guard.audit(roots=(root,),old_snapshots=(),dry_run=True)
            self.assertEqual(dry["would_restrict"],2)
            self.assertEqual(stat.S_IMODE(db.stat().st_mode),0o644)
            result=guard.audit(roots=(root,),old_snapshots=(),dry_run=False)
            self.assertEqual(result["restricted"],2)
            self.assertFalse(result["destructive_action_taken"])
            self.assertEqual(db.read_bytes(),b"SECRET_DB_CONTENT")
            self.assertEqual(env.read_text(),"SECRET_TEST_DUMMY=1")
            self.assertEqual(stat.S_IMODE(db.stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(normal.stat().st_mode),0o644)
            again=guard.audit(roots=(root,),old_snapshots=(),dry_run=False)
            self.assertEqual(again["restricted"],0)
    def test_does_not_follow_symlinks_or_modify_external_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            root=base/"backups";root.mkdir()
            external=base/"external.sqlite"
            external.write_bytes(b"outside")
            external.chmod(0o644)
            (root/"outside.sqlite").symlink_to(external)
            result=guard.audit(roots=(root,),old_snapshots=(),dry_run=False)
            self.assertEqual(result["skip_nonregular"],1)
            self.assertEqual(stat.S_IMODE(external.stat().st_mode),0o644)
    def test_missing_optional_root_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=guard.audit(roots=(Path(tmp)/"absent",),old_snapshots=(),dry_run=False)
            self.assertGreaterEqual(out["missing"],1)

if __name__=="__main__":unittest.main()
