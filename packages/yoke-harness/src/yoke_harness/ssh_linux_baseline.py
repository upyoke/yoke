"""Owner-only home archives and proved restore for Linux test users."""

from __future__ import annotations

import json
import shlex
from typing import Any

from yoke_harness.ssh_linux_reset_cleanup import RESET_WRITERS_PROGRAM
from yoke_harness.ssh_mac_baseline_probes import parse_baseline_probes
from yoke_harness.ssh_mac_full_reset_contract import GOLDEN_PROBES_SUFFIX
from yoke_harness.test_machine_types import HostActionResult

ABSENT_HOME_PATHS = (
    ".yoke",
    "yoke-server",
    ".yoke-e2e-logs",
    ".local/share/uv",
    ".local/state/uv",
    ".cache/uv",
    ".config/uv",
    ".local/bin/yoke",
    ".local/bin/uv",
    ".local/bin/uvx",
    ".local/bin/env",
)

_ARCHIVE_PROGRAM = r"""
import hashlib, json, os, pathlib, shutil, sys, tarfile, tempfile
operation, expected_home, golden = sys.argv[1:]
home = pathlib.Path(os.environ["HOME"])
baseline = pathlib.Path(golden)
absent = json.loads(sys.stdin.read())
def refuse(reason, entry=None):
    print(json.dumps({"ok": False, "reason": reason, "refused_entry": entry})); sys.exit(64)
if os.getuid() == 0 or str(home) != expected_home or len(home.parts) < 3 or home.is_symlink():
    refuse("linux_test_user_required")
if not baseline.is_absolute() or baseline == home or home in baseline.parents:
    refuse("golden_baseline_inside_home")
if baseline.is_symlink() or baseline.resolve() != baseline:
    refuse("golden_baseline_symlink_refused")
def validate_archive(archive):
    members = archive.getmembers()
    links = {pathlib.PurePosixPath(member.name) for member in members if member.issym()}
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        name = str(path)
        if any(parent in links for parent in path.parents):
            refuse("golden_baseline_archive_unsafe", member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] == ".ssh":
            refuse("golden_baseline_archive_unsafe", member.name)
        if not (member.isfile() or member.isdir() or member.issym()):
            refuse("golden_baseline_archive_unsafe", member.name)
        if member.issym():
            target = pathlib.Path(os.path.normpath(home / path.parent / member.linkname))
            if target != home and home not in target.parents:
                refuse("golden_baseline_archive_unsafe", member.name)
        if any(name == value or name.startswith(value + "/") for value in absent):
            refuse("golden_baseline_contains_yoke")
    return members
if operation not in {"capture", "reset"}: refuse("linux_golden_operation_unknown")
if operation == "capture":
    if baseline.exists(): refuse("golden_baseline_destination_exists")
    for value in absent:
        if (home / value).exists() or (home / value).is_symlink():
            refuse("golden_baseline_contains_yoke")
    baseline.parent.mkdir(parents=True, exist_ok=True)
    temporary = pathlib.Path(tempfile.mkdtemp(prefix=".yoke-golden-", dir=baseline.parent))
    try:
        def persistent_entry(member):
            # Socket links point into a live daemon's /tmp namespace, not saved login state.
            return None if member.issym() and member.name.endswith(".sock") else member
        with tarfile.open(temporary / "home.tar.gz", "w:gz") as archive:
            for entry in sorted(home.iterdir()):
                if entry.name == ".ssh": continue
                for directory, subdirs, files in os.walk(entry, followlinks=False):
                    for value in [directory, *[str(pathlib.Path(directory) / name) for name in subdirs + files]]:
                        if pathlib.Path(value).lstat().st_uid != os.getuid():
                            refuse("golden_capture_foreign_owner")
                if entry.lstat().st_uid != os.getuid(): refuse("golden_capture_foreign_owner")
                archive.add(entry, arcname=entry.name, filter=persistent_entry)
        with tarfile.open(temporary / "home.tar.gz", "r:gz") as archive:
            validate_archive(archive)
        digest = hashlib.file_digest((temporary / "home.tar.gz").open("rb"), "sha256").hexdigest()
        (temporary / "manifest.json").write_text(json.dumps({"os":"linux", "home": str(home), "uid": os.getuid(), "sha256":digest}))
        temporary.rename(baseline)
    finally:
        if temporary.exists(): shutil.rmtree(temporary)
else:
    if not baseline.is_dir(): refuse("golden_baseline_unavailable")
    manifest = json.loads((baseline / "manifest.json").read_text())
    digest = hashlib.file_digest((baseline / "home.tar.gz").open("rb"), "sha256").hexdigest()
    if manifest != {"os":"linux", "home":str(home), "uid":os.getuid(), "sha256":digest}:
        refuse("golden_baseline_identity_mismatch")
    with tarfile.open(baseline / "home.tar.gz", "r:gz") as archive:
        members = validate_archive(archive)
        # STOP_YOKE_WRITERS
        for entry in home.iterdir():
            if entry.name == ".ssh": continue
            if entry.is_dir() and not entry.is_symlink(): shutil.rmtree(entry)
            else: entry.unlink()
        archive.extractall(home, filter="fully_trusted")
        for member in members:
            restored = home / member.name
            if member.isfile():
                with archive.extractfile(member) as original, restored.open("rb") as actual:
                    if hashlib.file_digest(original, "sha256").digest() != hashlib.file_digest(actual, "sha256").digest():
                        refuse("linux_golden_restore_not_proved")
            elif member.issym() and os.readlink(restored) != member.linkname:
                refuse("linux_golden_restore_not_proved")
    for value in absent:
        if (home / value).exists() or (home / value).is_symlink(): refuse("reset_absence_not_proved")
print(json.dumps({"ok":True, "operation":operation, "golden_baseline_path":str(baseline),
                  "preserved_entries":[".ssh"], "absent_paths":absent if operation == "reset" else []}))
"""


def prove_linux_probes(control: Any, document: str) -> HostActionResult:
    """Run declared credential/CLI/service checks through the SSH user session."""
    try:
        probes = parse_baseline_probes(document)
    except ValueError:
        return HostActionResult(
            False,
            {"recovery": "Correct the baseline probes document."},
            "baseline_probes_invalid",
        )
    rows = []
    for probe in probes:
        result = control.run_command(probe.argv, timeout=120)
        matched = (
            probe.expect_output_contains is None
            or probe.expect_output_contains
            in ((result.stdout or "") + (result.stderr or ""))
        )
        ok = result.returncode == 0 and matched
        rows.append(
            {
                "name": probe.name,
                "ok": ok,
                "exit_code": result.returncode,
                "expectation_met": matched,
            }
        )
        if not ok:
            return HostActionResult(
                False,
                {
                    "probes": rows,
                    "recovery": "Sign in again or repair the declared CLI/service, then recapture the golden.",
                },
                "baseline_probe_failed",
            )
    return HostActionResult(True, {"probes": rows})


def archive_operation(
    control: Any, operation: str, destination: str
) -> HostActionResult:
    command = shlex.join(
        [
            "/usr/bin/python3",
            "-c",
            _ARCHIVE_PROGRAM.replace(
                "        # STOP_YOKE_WRITERS",
                "\n".join(
                    "        " + line for line in RESET_WRITERS_PROGRAM.splitlines()
                ),
            ),
            operation,
            control.home,
            destination,
        ]
    )
    result = control._run(
        command, input_text=json.dumps(ABSENT_HOME_PATHS), timeout=300
    )
    try:
        evidence = json.loads(result.stdout)
    except (ValueError, TypeError):
        evidence = {"reason": "linux_golden_operation_failed"}
    if not isinstance(evidence, dict):
        evidence = {"reason": "linux_golden_receipt_invalid"}
    ok = result.returncode == 0 and evidence.get("ok") is True
    if not ok:
        evidence["recovery"] = (
            "Use a non-root test user and a new literal golden directory outside its home; repair the baseline archive before retrying."
        )
    return HostActionResult(
        ok,
        evidence,
        None if ok else evidence.get("reason", "linux_golden_operation_failed"),
    )


def capture_linux_golden(
    control: Any, destination: str, probes_document: str | None
) -> HostActionResult:
    if probes_document is None:
        return HostActionResult(
            False,
            {
                "recovery": "Pass --probes-file with CLI, credential and relevant user-service checks."
            },
            "baseline_probes_not_declared",
        )
    proven = prove_linux_probes(control, probes_document)
    if not proven.ok:
        return proven
    captured = archive_operation(control, "capture", destination)
    if not captured.ok:
        return captured
    try:
        control.upload_remote_text(destination + GOLDEN_PROBES_SUFFIX, probes_document)
    except RuntimeError:
        return HostActionResult(
            False,
            {
                **captured.evidence,
                "recovery": "Write the probes beside the golden or capture a new golden before resetting.",
            },
            "golden_probes_write_failed",
        )
    return HostActionResult(
        True, {**captured.evidence, "user_equivalence": proven.evidence}
    )
