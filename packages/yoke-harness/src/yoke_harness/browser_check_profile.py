"""Private, machine-local browser profiles for individual QA checks."""

from __future__ import annotations

import json
import os
import shutil
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from yoke_cli.config import machine_config
from yoke_cli.config.browser_profile import (
    profile_project_key,
    resolve_authorized_profile,
)
from yoke_cli.config.browser_profile_cookies import (
    SignInCookieError,
    keep_sign_in_cookies,
)
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.machine_config.schema import SECRETS_DIR_NAME
from yoke_contracts.process_ancestry import process_start_time
from yoke_harness.browser_daemon_profile import profile_scope


@dataclass
class BrowserCheck:
    check_id: str
    directory: Path

    @property
    def profile(self) -> Path:
        return self.directory / "profile"


def _root(*, create: bool = True) -> Path:
    root = machine_config.yoke_home() / SECRETS_DIR_NAME / "browser-checks"
    if create:
        create_private_directory(root)
    return root


def _copy_profile(source: Path, destination: Path) -> None:
    """Copy regular profile files, excluding Chromium locks and IPC endpoints."""
    create_private_directory(destination)
    for entry in source.iterdir():
        if entry.name.startswith("Singleton") or entry.is_symlink():
            continue
        mode = entry.stat().st_mode
        target = destination / entry.name
        if stat.S_ISDIR(mode):
            _copy_profile(entry, target)
        elif stat.S_ISREG(mode):
            with entry.open("rb") as src, target.open("xb") as dst:
                os.chmod(target, 0o600)
                shutil.copyfileobj(src, dst)


def _owner(pid: int) -> dict:
    start = process_start_time(pid)
    if start is None:
        raise RuntimeError(
            "browser_check_owner_unavailable: cannot inspect the browser check's "
            "owning process; restore local process-query access, then retry."
        )
    return {"pid": pid, "start": start}


def _write_record(check: BrowserCheck, record: dict) -> None:
    path = check.directory / "owner.json"
    temporary = check.directory / "owner.tmp"
    temporary.write_text(json.dumps(record), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def record_daemon_owner(profile: str, pid: int) -> None:
    """Keep the daemon's birth token so a reused pid can never be signalled."""
    if not profile:
        return
    directory = Path(profile).resolve().parent
    if directory.parent != _root(create=False).resolve():
        return
    check = BrowserCheck(directory.name, directory)
    try:
        record = json.loads((directory / "owner.json").read_text())
        record["daemon"] = _owner(pid)
        _write_record(check, record)
    except (OSError, ValueError):
        raise RuntimeError(
            "browser_check_owner_unavailable: the private daemon's owner record "
            "is unreadable; restore owner access to the Yoke secret directory "
            "and start a new check."
        ) from None


def _remove(check: BrowserCheck) -> None:
    from yoke_harness import browser_client

    try:
        state_path = browser_client._state_file_path(str(check.profile))
        state = browser_client.DaemonState.load(state_path)
        if state and browser_client.daemon_running(state):
            record = json.loads((check.directory / "owner.json").read_text())
            daemon = record.get("daemon")
            if not daemon:
                raise RuntimeError(
                    "browser_check_owner_unavailable: this daemon has no recorded "
                    "birth token; wait for its idle exit, then retry the check "
                    "to sweep the abandoned copy."
                )
            if daemon["pid"] == state.pid and daemon["start"] == process_start_time(
                state.pid
            ):
                try:
                    browser_client.daemon_stop(profile_dir=str(check.profile))
                except RuntimeError as exc:
                    if str(exc) != "daemon not running":
                        raise
        if state_path.parent.exists():
            shutil.rmtree(state_path.parent)
        shutil.rmtree(check.directory)
    except OSError:
        raise RuntimeError(
            "browser_check_cleanup_failed: restore owner access and free disk "
            "space in the Yoke secret directory, then rerun the check to sweep "
            "abandoned copies."
        ) from None


def sweep_checks() -> None:
    """Reap only copies whose recorded owning process died or was replaced."""
    for directory in _root().iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            UUID(directory.name)
            record = json.loads((directory / "owner.json").read_text())
        except (ValueError, OSError):
            continue  # A concurrent creator has not published its owner yet.
        owner = record["owner"]
        if process_start_time(owner["pid"]) != owner["start"] or not owner["start"]:
            _remove(BrowserCheck(directory.name, directory))


@contextmanager
def check_scope(project, identity=None, *, check_id=None, keep_open=False):
    """Copy sign-in once per check, route calls privately, and clean up on exit.

    A CLI step sequence retains its opaque check id until its final call. Its
    daemon owns that copy between calls; an idle exit makes it sweepable.
    """
    from yoke_contracts.browser_identity import DEFAULT_IDENTITY, validate_identity_name
    from yoke_harness import browser_client

    identity = validate_identity_name(identity or DEFAULT_IDENTITY)
    project = profile_project_key(project)
    check = None
    retain = False
    try:
        sweep_checks()
        if check_id:
            try:
                check_id = str(UUID(check_id))
                check = BrowserCheck(check_id, _root() / check_id)
                if check.directory.is_symlink():
                    check = None
                    raise ValueError("check cannot be a link")
                record = json.loads((check.directory / "owner.json").read_text())
            except (ValueError, OSError):
                raise RuntimeError(
                    "browser_check_unavailable: this check ended; start a new "
                    "sequence without --check-id."
                ) from None
            if record["project"] != str(project) or record["identity"] != identity:
                check = None
                raise RuntimeError(
                    "browser_check_identity_mismatch: use the project's original "
                    "identity or start a new sequence without --check-id."
                )
        else:
            source, _ = resolve_authorized_profile(project, identity=identity)
            check_id = str(uuid4())
            check = BrowserCheck(check_id, _root() / check_id)
            create_private_directory(check.directory)
            record = {
                "project": str(project),
                "identity": identity,
                "owner": _owner(os.getpid()),
            }
            _write_record(check, record)
            if source:
                _copy_profile(source, check.profile)
                try:
                    keep_sign_in_cookies(check.profile)
                except SignInCookieError:
                    raise RuntimeError(
                        "browser_check_sign_in_copy_failed: copied cookies could "
                        "not be prepared; close the sign-in window and run "
                        "`yoke browser authorize`, then start a new check."
                    ) from None
            else:
                create_private_directory(check.profile)
        with profile_scope(check.profile):
            yield check
            if keep_open:
                state = browser_client.DaemonState.load(
                    browser_client._state_file_path()
                )
                if state is None or not browser_client.daemon_running(state):
                    raise RuntimeError(
                        "browser_check_unavailable: browser exited; start a new "
                        "sequence without --check-id."
                    )
                record = json.loads((check.directory / "owner.json").read_text())
                record["owner"] = _owner(state.pid)
                record["daemon"] = record["owner"]
                _write_record(check, record)
                retain = True
    except OSError:
        raise RuntimeError(
            "browser_check_copy_failed: could not prepare or remove the private "
            "browser copy; check free disk space and owner access to the Yoke "
            "secret directory, then retry."
        ) from None
    finally:
        if check and check.directory.exists() and not retain:
            _remove(check)
