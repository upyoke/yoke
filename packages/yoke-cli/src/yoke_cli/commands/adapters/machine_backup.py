"""Offline machine backup/restore CLI adapters."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config import machine_backup as storage
from yoke_cli.config.machine_backup_files import MachineBackupError
from yoke_contracts.refusal_recovery import compose_refusal

BACKUP_USAGE = "yoke machine backup --to FOLDER"
RESTORE_USAGE = "yoke machine restore --from FOLDER [--replace]"
TOOL_SHAPED_USAGE = {
    "yoke machine backup": BACKUP_USAGE,
    "yoke machine restore": RESTORE_USAGE,
}


def _run(args: list[str], *, restoring: bool) -> int:
    verb = "restore" if restoring else "backup"
    usage = RESTORE_USAGE if restoring else BACKUP_USAGE
    parser = argparse.ArgumentParser(prog=f"yoke machine {verb}", usage=usage)
    parser.add_argument("--from" if restoring else "--to", dest="folder", required=True)
    if restoring:
        parser.add_argument(
            "--replace", action="store_true", help="Replace differing existing files."
        )
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        if restoring:
            result = storage.restore(Path(parsed.folder), replace=parsed.replace)
        else:
            result = storage.backup(Path(parsed.folder))
    except MachineBackupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, AttributeError):
        print(
            compose_refusal(
                f"machine_{verb}_failed: unable to process the backup files or configuration",
                recovery="check file access and config.json structure, then retry",
            ),
            file=sys.stderr,
        )
        return 1
    print(f"machine {verb}: {result['files']} files; {result['changed']} changed")
    for name in result["missing"]:
        print(f"missing referenced file (skipped by backup): {name}")
    if not restoring:
        return 0
    print("GitHub authorization was excluded: run `yoke github connect`.")
    print(
        "Browser profiles were excluded: run `yoke browser authorize --help` to sign in again."
    )
    print(
        "Running `yoke doctor run --only connections`; diagnostic contents are kept out of restore output.",
        flush=True,
    )
    try:
        doctor = subprocess.run(
            ["yoke", "doctor", "run", "--only", "connections"],
            capture_output=True,
            timeout=120,
            check=False,
            cwd=Path.home(),
        )
        if doctor.returncode == 0:
            print("machine restore: doctor passed")
            return 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    print(
        compose_refusal(
            "machine_restore_doctor_failed: files restored; restored connection health is unverified",
            recovery="run `yoke doctor run --only connections` and follow its named repairs; authorize GitHub with `yoke github connect`",
        ),
        file=sys.stderr,
    )
    return 1


def machine_backup(args: list[str]) -> int:
    return _run(args, restoring=False)


def machine_restore(args: list[str]) -> int:
    return _run(args, restoring=True)


TOOL_SHAPED_SUBCOMMANDS = {
    ("machine", "backup"): machine_backup,
    ("machine", "restore"): machine_restore,
}
