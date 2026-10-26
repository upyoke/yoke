"""Volatile macOS caches are omitted, not preserved, by golden capture."""

from __future__ import annotations

import json
import shlex
import sys
from threading import Event, Thread

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    require_zsh,
    run_functions,
)
from runtime.api.domain.test_ssh_mac_golden_capture_copy import _run_capture
from yoke_harness.ssh_mac_golden_capture_receipt import closed_capture_outcomes
from yoke_harness.ssh_mac_preserved_state import (
    PRESERVED_HOME_ENTRIES,
    PRESERVED_MANIFEST_KEY,
    PRESERVED_MANIFEST_VALUE,
    render_preserved_state_contract,
)


def test_capture_prunes_caches_without_preserving_them(tmp_path):
    require_zsh()
    home = tmp_path / "home"
    cache = home / "Library/Caches/com.apple.duetexpertd/transient"
    cache.parent.mkdir(parents=True)
    cache.write_text("volatile")
    neighbor = home / "Library/Caches-neighbor"
    neighbor.write_text("capture me")
    result = run_functions(
        (
            render_preserved_state_contract(),
            f"cd -- {shlex.quote(str(home))}",
            "list_capture_entries",
            'print -r -- "$preserved_manifest_line"',
        ),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    entries, manifest = result.stdout.rsplit("\0", 1)
    assert set(entries.split("\0")) == {"./Library", "./Library/Caches-neighbor"}
    assert "Library/Caches" not in PRESERVED_HOME_ENTRIES
    assert json.loads(PRESERVED_MANIFEST_VALUE) == list(PRESERVED_HOME_ENTRIES)
    assert manifest.strip() == f"{PRESERVED_MANIFEST_KEY} {PRESERVED_MANIFEST_VALUE}"


@pytest.mark.skipif(sys.platform != "darwin", reason="uses macOS tar metadata")
def test_capture_succeeds_while_cache_files_appear_and_disappear(tmp_path):
    home = tmp_path / "home"
    caches = home / "Library/Caches/com.apple.duetexpertd"
    caches.mkdir(parents=True)
    (home / "state").write_text("restore me")
    stop, active = Event(), Event()

    def churn():
        while not stop.is_set():
            transient = caches / "transient"
            transient.write_text("volatile")
            transient.unlink()
            active.set()

    worker = Thread(target=churn)
    worker.start()
    try:
        assert active.wait(timeout=5)
        destination = tmp_path / "golden"
        result = _run_capture(home, destination, tmp_path)
    finally:
        stop.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert closed_capture_outcomes(result.stdout) is not None
    assert (destination / "state").read_text() == "restore me"
    assert not (destination / "Library/Caches").exists()
    manifest = destination.with_suffix(".manifest").read_text()
    assert f"{PRESERVED_MANIFEST_KEY} {PRESERVED_MANIFEST_VALUE}" in manifest
    assert "Library/Caches" not in manifest
