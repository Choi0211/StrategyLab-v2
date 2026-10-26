#!/usr/bin/env python3
"""Protect selected Gaon snapshot backups from local cross-user reads.

No backup deletion, file content reads, trading access, SQLite locks,
ownership changes, network access, service restarts or speculative cleanup.
Works under systemd with a root service confined to explicit backup roots.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys

SOURCES=(
    Path("/opt/strategylab-v2/deploy_backups"),
    Path("/var/lib/strategylab/backups"),
)
OLD_SNAPSHOTS=(
    Path("/var/lib/strategylab/gaon-runtime-pre-learning-v3-20261018.sqlite"),
    Path("/var/lib/strategylab/gaon-runtime-pre-research-fix-20261017.sqlite"),
)
FILE_SUFFIXES=(".sqlite",".db",".sqlite3",".env")
# .env backup suffix: gaon-web.env.before-...
def sensitive_file(p: Path)->bool:
    name=p.name.lower()
    return (name.endswith(FILE_SUFFIXES)
            or ".sqlite." in name or ".db." in name
            or ".env." in name or name.endswith(".env.backup"))

def protect_file(p: Path,*,dry_run:bool)->str:
    # lstat, never follow symbolic links or replace existing backup contents.
    try: info=p.lstat()
    except FileNotFoundError:return "missing"
    if not stat.S_ISREG(info.st_mode):return "skip_nonregular"
    mode=stat.S_IMODE(info.st_mode)
    if mode&0o077==0:return "already_private"
    if not dry_run:
        os.chmod(p,mode&~0o077,follow_symlinks=False)
        after=p.lstat()
        if stat.S_IMODE(after.st_mode)&0o077:
            raise RuntimeError(f"access not restricted for {p}")
    return "would_restrict" if dry_run else "restricted"

def audit(*,roots=SOURCES,old_snapshots=OLD_SNAPSHOTS,dry_run=False):
    totals={k:0 for k in ("restricted","would_restrict","already_private","missing","skip_nonregular")}
    inspected=0
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            totals["missing"]+=1
            continue
        for path in root.rglob("*"):
            if not sensitive_file(path):
                continue
            inspected+=1
            key=protect_file(path,dry_run=dry_run)
            totals[key]+=1
    for path in old_snapshots:
        inspected+=1
        key=protect_file(path,dry_run=dry_run)
        totals[key]+=1
    return {"files_inspected":inspected,**totals,"destructive_action_taken":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    os.umask(0o077)
    print(audit(dry_run=args.dry_run))
    return 0
if __name__=="__main__":
    sys.exit(main())
