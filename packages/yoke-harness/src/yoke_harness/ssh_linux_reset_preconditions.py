"""Read-only Linux reset admission and opaque live Claude credential retention."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
import shlex
import subprocess
from typing import Any

from yoke_harness.baseline_harness_requests import harness_request
from yoke_harness.ssh_mac_baseline_probes import (
    GOLDEN_PROBES_SUFFIX,
    PROBE_TIMEOUT_SECONDS,
    parse_baseline_probes,
)
from yoke_harness.test_machine_types import HostActionResult

# Shared by the read-only admission call and the final check before teardown.
DESKTOP_PROGRAM = r"""
import subprocess
def desktop_precondition():
    def logged_in():
        refuse("linux_reset_desktop_logged_in", recovery="operator is logged in to the desktop; log out first")
    redirected = str(home / "thinclient_drives")
    try:
        if os.path.ismount(redirected): logged_in()
        proc = pathlib.Path("/proc")
        if proc.exists():
            for line in (proc / "self/mountinfo").read_text().splitlines():
                target = line.split()[4].replace("\\040", " ").replace("\\134", "\\")
                if target == redirected or target.startswith(redirected + "/"): logged_in()
            for directory in proc.iterdir():
                if not directory.name.isdigit(): continue
                try:
                    if directory.stat().st_uid == os.getuid() and (directory / "comm").read_text().strip() == "xfce4-session":
                        logged_in()
                except (FileNotFoundError, ProcessLookupError): pass
        if shutil.which("loginctl") and pathlib.Path("/run/systemd/system").is_dir():
            sessions = subprocess.run(["loginctl", "list-sessions", "--no-legend", "--no-pager"], capture_output=True, text=True, timeout=10)
            if sessions.returncode: raise OSError()
            for line in sessions.stdout.splitlines():
                fields = line.split()
                if len(fields) < 2 or fields[1] != str(os.getuid()): continue
                result = subprocess.run(["loginctl", "show-session", fields[0], "--no-pager", "-p", "Type", "-p", "Active"], capture_output=True, text=True, timeout=10)
                if result.returncode: raise OSError()
                properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
                if properties.get("Type") in {"x11", "wayland"} and properties.get("Active") == "yes": logged_in()
    except (OSError, subprocess.TimeoutExpired):
        refuse("linux_reset_desktop_state_unknown", recovery="Repair /proc or loginctl access, then retry; desktop logout was not proved.")
"""

CREDENTIAL_PROGRAM = r"""
credential_relative = pathlib.Path(".claude/.credentials.json")
def credential_path():
    path = home
    for part in credential_relative.parts:
        path = path / part
        if path.is_symlink(): refuse("linux_claude_credentials_unsafe", recovery="Repair the owner-only regular Claude credential file, then retry.")
        if path.exists() and path.stat().st_uid != os.getuid():
            refuse("linux_claude_credentials_unsafe", recovery="Repair the Claude credential owner, then retry.")
    return path
def stash_claude():
    source = credential_path()
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                refuse("linux_claude_credentials_unsafe", recovery="Set the live Claude credential file owner to this user and mode 0600, then retry.")
            for member in members:
                if member.name == ".claude" and not member.isdir() or member.name == str(credential_relative) and not member.isfile():
                    refuse("linux_claude_credentials_unsafe", recovery="Repair the golden's Claude storage path before retrying.")
            directory = pathlib.Path(tempfile.mkdtemp(prefix="yoke-live-claude-", dir="/tmp"))
            saved = directory / "credentials"
            with os.fdopen(os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                shutil.copyfileobj(stream, output)
        return directory, info.st_uid, info.st_gid
    except OSError:
        refuse("linux_claude_credentials_unavailable", recovery="Operator must sign in again; the live owner-only Claude credential file is unavailable.")
def restore_claude(stash):
    directory, uid, gid = stash
    try:
        destination = credential_path()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = destination.parent / (".credentials-" + directory.name)
        with (directory / "credentials").open("rb") as source, os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as output:
            shutil.copyfileobj(source, output)
            os.fchown(output.fileno(), uid, gid)
            os.fchmod(output.fileno(), 0o600)
        temporary.replace(destination)
        shutil.rmtree(directory)
    except OSError:
        refuse("linux_claude_credentials_restore_failed", recovery="Restore the owner-only credential stash at " + str(directory) + " to ~/.claude/.credentials.json with its original owner and mode 0600, then remove the stash before retrying.")
"""


def reset_preflight(control: Any, destination: str) -> HostActionResult:
    """Refuse before archive cleanup; select Claude solely from sealed probes."""
    program = (
        "import json, os, pathlib, shutil, sys\nhome = pathlib.Path(sys.argv[1])\n"
        "def refuse(reason, entry=None, recovery=None):\n"
        ' print(json.dumps({"ok":False,"reason":reason,"recovery":recovery})); sys.exit(64)\n'
        + DESKTOP_PROGRAM
        + '\ndesktop_precondition()\nprint(json.dumps({"ok":True}))\n'
    )
    observed = control._run(
        shlex.join(["/usr/bin/python3", "-c", program, control.home])
    )
    try:
        evidence = json.loads(observed.stdout)
    except (ValueError, TypeError):
        evidence = {}
    if not isinstance(evidence, dict):
        evidence = {}
    if observed.returncode or evidence.get("ok") is not True:
        evidence.setdefault(
            "recovery",
            "Repair the read-only Linux desktop admission command, then retry.",
        )
        return HostActionResult(
            False, evidence, evidence.get("reason", "linux_golden_operation_failed")
        )
    try:
        document = control.read_remote_text(destination + GOLDEN_PROBES_SUFFIX)
    except RuntimeError:
        return HostActionResult(
            False,
            {"recovery": "Repair the sealed baseline probes file access, then retry."},
            "baseline_probes_unavailable",
        )
    try:
        probes = parse_baseline_probes(document)
    except ValueError:
        return HostActionResult(
            False,
            {
                "recovery": "Repair the sealed baseline probes document before resetting."
            },
            "baseline_probes_invalid",
        )
    claude = next(
        (probe for probe in probes if PurePosixPath(probe.argv[0]).name == "claude"),
        None,
    )
    if claude is None:
        return HostActionResult(True, {"preserve_claude": False})
    request = harness_request(claude.argv)
    try:
        result = control.run_command(request.argv, timeout=PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return _request_failure("timeout", "Claude request timed out.")
    except Exception:
        return _request_failure(
            "transport", "Claude request could not be delivered over SSH."
        )
    if result.returncode == 0 and request.answered(result.stdout or ""):
        return HostActionResult(True, {"preserve_claude": True})
    # Read only diagnosed error fields, never successful events/account reports.
    errors = (result.stderr or "").splitlines()
    for line in (result.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            errors.append(line)
            continue
        if isinstance(event, dict) and event.get("is_error"):
            errors.extend(str(event.get("result", "")).splitlines())
    for cause, markers in (
        (
            "auth",
            (
                "oauth session expired",
                "invalid refresh token",
                "not logged in",
                "authentication failed",
                "invalid api key",
                "please run /login",
            ),
        ),
        (
            "network",
            (
                "network",
                "connection",
                "enotfound",
                "econn",
                "fetch failed",
                "timed out",
                "timeout",
            ),
        ),
    ):
        error = next(
            (
                line.strip()
                for line in errors
                if any(marker in line.lower() for marker in markers)
            ),
            None,
        )
        if error:
            return _request_failure(cause, error)
    return _request_failure(
        "request",
        next(
            (line.strip() for line in errors if line.strip()),
            "Claude request failed without an authentication or network diagnosis.",
        ),
    )


def _request_failure(cause: str, error: str) -> HostActionResult:
    # Diagnose the CLI error, never expose token-shaped material/account identity.
    error = re.sub(
        r"(?i)(?:sk-|eyJ)[A-Za-z0-9._-]+|[\w.+-]+@[\w.-]+|https?://\S+|(?<=Bearer )\S+",
        "[REDACTED]",
        error,
    )[:500]
    recovery = (
        "Claude sign-in on this machine is no longer valid; operator must sign in again."
        if cause == "auth"
        else "Repair the named Claude request failure and retry; the home has not been cleared."
    )
    return HostActionResult(
        False,
        {"reason": error, "recovery": recovery},
        f"linux_reset_claude_{cause}_failed",
    )
