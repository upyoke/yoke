"""Filesystem proof that live harness logins survive a reset and stay uncaptured."""

from __future__ import annotations

import json
from pathlib import Path
import shlex

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment,
    function_program,
    require_zsh,
    run_functions,
)
from yoke_contracts.browser_identity import LIVE_IDENTITY_STORE_HOME_ENTRY as STORE
from yoke_harness.ssh_mac_preserved_state import (
    HARNESS_LOGIN_HOME_ENTRIES,
    PRESERVED_HOME_ENTRIES,
    PRESERVED_MANIFEST_KEY,
    PRESERVED_MANIFEST_VALUE,
)

KEYCHAIN = "Library/Keychains/login.keychain-db"
LOGIN_FILES = (KEYCHAIN, ".claude/.credentials.json", ".codex/auth.json")
NEIGHBORS = (
    ".claude/settings.json",
    ".codex/config.toml",
    "Library/Preferences/a.plist",
)


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _program(home: Path) -> tuple[str, ...]:
    require_zsh()
    return (function_program(), assignment("home", str(home)), "failure_detail=''")


def test_every_harness_login_is_a_preserved_entry():
    assert set(HARNESS_LOGIN_HOME_ENTRIES) <= set(PRESERVED_HOME_ENTRIES)
    assert all(
        any(path == e or path.startswith(e + "/") for e in HARNESS_LOGIN_HOME_ENTRIES)
        for path in LOGIN_FILES
    )


def test_reset_keeps_each_live_login_and_restores_everything_else(tmp_path):
    home, golden = tmp_path / "home", tmp_path / "golden"
    for relative in (".ssh/authorized_keys", *LOGIN_FILES, *NEIGHBORS):
        _write(home, relative, "live")
        _write(golden, relative, "golden")
    _write(home, "Library/Keychains/metadata.keychain-db", "live metadata")
    _write(home, ".claude/contaminant", "remove")
    error = tmp_path / "restore-errors"
    result = run_functions(
        (
            *_program(home),
            assignment("golden", str(golden)),
            assignment("restore_error_log", str(error)),
            assignment("restore_failure_report", str(error) + ".entries"),
            ': > "$restore_error_log"',
            ': > "$restore_failure_report"',
            "clear_home_levels",
            "restore_golden_levels",
        ),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    for relative in LOGIN_FILES:
        assert (home / relative).read_text() == "live", relative
    assert (home / "Library/Keychains/metadata.keychain-db").exists()
    for relative in NEIGHBORS:
        assert (home / relative).read_text() == "golden", relative
    assert not (home / ".claude/contaminant").exists()
    assert error.read_text() == ""


def test_a_host_without_harness_logins_still_verifies_its_required_entries(tmp_path):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / "Library/Application Support/com.apple.TCC").mkdir(parents=True)
    result = run_functions(
        (
            *_program(home),
            'for suffix in "${required_preserved_entries[@]}"; do',
            '  lexists "$home/$suffix" || print -r -- MISSING',
            "done",
        ),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    assert "MISSING" not in result.stdout


def test_capture_prunes_every_preserved_entry_and_keeps_neighbors(tmp_path):
    home = tmp_path / "home"
    for relative in (".ssh/id", *LOGIN_FILES, *NEIGHBORS):
        _write(home, relative, "state")
    result = run_functions(
        (*_program(home), f"cd -- {shlex.quote(str(home))}", "list_capture_entries"),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    entries = {entry.removeprefix("./") for entry in result.stdout.split("\0") if entry}
    for kept in (".ssh", ".ssh/id", "Library/Keychains", *LOGIN_FILES):
        assert kept not in entries, kept
    for neighbor in (".claude", ".codex", *NEIGHBORS):
        assert neighbor in entries, neighbor


@pytest.mark.parametrize(
    "manifest",
    [
        "legacy",
        "declared",
        "earlier_subset",
        "mismatch",
        "copied_login",
        "copied_store",
    ],
)
def test_reset_manifest_refuses_a_golden_carrying_a_declared_login(tmp_path, manifest):
    home, golden = tmp_path / "home", tmp_path / "golden"
    home.mkdir()
    golden.mkdir()
    line = f"{PRESERVED_MANIFEST_KEY} {PRESERVED_MANIFEST_VALUE}"
    if manifest == "legacy":
        line = "source_home legacy"
    if manifest == "earlier_subset":
        # Sealed before the identity store joined the kept set.
        earlier = [entry for entry in PRESERVED_HOME_ENTRIES if entry != STORE]
        line = f"{PRESERVED_MANIFEST_KEY} {json.dumps(earlier, separators=(',', ':'))}"
    if manifest == "mismatch":
        line = f'{PRESERVED_MANIFEST_KEY} [".ssh","Library/Unknown"]'
    if manifest == "copied_login":
        _write(golden, ".codex/auth.json", "captured login")
    if manifest == "copied_store":
        _write(golden, f"{STORE}/acme/admin/Cookies", "captured cookies")
    Path(str(golden) + ".manifest").write_text(line + "\n")
    result = run_functions(
        (
            *_program(home),
            assignment("golden", str(golden)),
            "manifest_suffix=.manifest",
            "validate_preserved_manifest || print -r -- REJECTED",
        ),
        shell_home=tmp_path / "shell",
    )
    assert ("REJECTED" in result.stdout) == (
        manifest in {"mismatch", "copied_login", "copied_store"}
    )
