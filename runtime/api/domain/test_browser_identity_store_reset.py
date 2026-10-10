"""The live browser identity store survives full resets and never enters a golden."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment,
    function_program,
    require_zsh,
    run_functions,
)
from yoke_contracts.browser_identity import LIVE_IDENTITY_STORE_HOME_ENTRY as STORE
from yoke_harness.ssh_linux_baseline import ABSENT_HOME_PATHS, _ARCHIVE_PROGRAM
from yoke_harness.ssh_mac_full_reset_contract import YOKE_ABSENT_RELATIVE_DIRECTORIES
from yoke_harness.ssh_mac_preserved_state import (
    LIVE_IDENTITY_HOME_ENTRIES,
    PRESERVED_HOME_ENTRIES,
    REQUIRED_PRESERVED_HOME_ENTRIES,
)

COOKIES = f"{STORE}/acme/admin/Default/Cookies"


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_store_is_kept_live_and_lives_outside_the_absent_yoke_home():
    assert set(LIVE_IDENTITY_HOME_ENTRIES) == {STORE}
    assert STORE in PRESERVED_HOME_ENTRIES
    assert STORE not in REQUIRED_PRESERVED_HOME_ENTRIES
    assert not any(
        STORE == absent or STORE.startswith(absent + "/")
        for absent in (*YOKE_ABSENT_RELATIVE_DIRECTORIES, *ABSENT_HOME_PATHS)
    )


def test_mac_reset_keeps_the_live_store_and_capture_prunes_it(tmp_path):
    require_zsh()
    home, golden = tmp_path / "home", tmp_path / "golden"
    _write(home, COOKIES, "refreshed during the last walk")
    _write(home, ".yoke/secrets/residue", "removed")
    _write(golden, "Documents/note", "golden")
    error = tmp_path / "restore-errors"
    program = (function_program(), assignment("home", str(home)), "failure_detail=''")
    result = run_functions(
        (
            *program,
            assignment("golden", str(golden)),
            assignment("restore_error_log", str(error)),
            assignment("restore_failure_report", str(error) + ".entries"),
            ': > "$restore_error_log"',
            ': > "$restore_failure_report"',
            "clear_home_levels",
            "restore_golden_levels",
            f"cd -- {home}",
            "list_capture_entries",
        ),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    assert (home / COOKIES).read_text() == "refreshed during the last walk"
    assert not (home / ".yoke").exists()
    assert (home / "Documents/note").read_text() == "golden"
    captured = {entry.removeprefix("./") for entry in result.stdout.split("\0")}
    assert not any(entry.startswith(STORE) for entry in captured if entry)


def _archive_run(home: Path, golden: Path, operation: str):
    # This is the fake remote's interpreter; it only owns pytest's temp home.
    return subprocess.run(
        [sys.executable, "-c", _ARCHIVE_PROGRAM, operation, str(home), str(golden)],
        input=json.dumps(ABSENT_HOME_PATHS),
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )


@pytest.mark.skipif(os.getuid() == 0, reason="archive fixture needs a non-root user")
def test_linux_capture_omits_the_store_and_reset_keeps_it_live(tmp_path):
    home, golden = tmp_path / "home", tmp_path / "golden"
    _write(home, COOKIES, "signed in at capture")
    _write(home, ".ssh/authorized_keys", "key")
    _write(home, "notes.txt", "golden")
    captured = _archive_run(home, golden, "capture")
    assert captured.returncode == 0, captured.stdout + captured.stderr
    with tarfile.open(golden / "home.tar.gz") as archive:
        assert not any(name.startswith(STORE) for name in archive.getnames())
    _write(home, COOKIES, "rotated by the site during a walk")
    _write(home, ".yoke/secrets/residue", "removed")
    restored = _archive_run(home, golden, "reset")
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert (home / COOKIES).read_text() == "rotated by the site during a walk"
    assert not (home / ".yoke").exists()
    assert (home / "notes.txt").read_text() == "golden"
    assert STORE in json.loads(restored.stdout)["preserved_entries"]
