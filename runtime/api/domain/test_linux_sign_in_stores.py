"""Linux harness sign-ins stay live through reset and never enter a golden."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import tarfile
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_harness.baseline_probe_failure_causes import PROBE_EXIT_CODES
from yoke_harness.ssh_linux_baseline import _ARCHIVE_PROGRAM, archive_operation
from yoke_harness.ssh_mac_sign_in_apps import SIGN_IN_APP_QUIT_NOT_PROVED
from yoke_harness.standard_baseline_probes import standard_probes

SEALED_PROBES = standard_probes("linux")
CLAUDE, CODEX, CURSOR = SIGN_INS = (
    ".claude/.credentials.json",
    ".codex/auth.json",
    ".config/cursor/auth.json",
)
SIGNED_OUT = PROBE_EXIT_CODES["probe_harness_exit_nonzero"]


def sealed_host(home: Path, signed_in: set[str]) -> SimpleNamespace:
    """A Linux host whose sealed probes pass only for *signed_in* harnesses.

    The archive command runs the real program against the pytest home, without
    the remote-only writer stop that would reach this machine's daemons.
    """
    probes = {tuple(probe["argv"]): probe["name"] for probe in SEALED_PROBES}
    host = SimpleNamespace(home=str(home), probed=[], archive_runs=0, calls=[])
    host.chromium_quit = '{"ok": true, "quit": true}'

    def run_command(argv, timeout=None):
        name = probes[tuple(argv)]
        host.probed.append(name)
        return subprocess.CompletedProcess(
            argv, 0 if name in signed_in else SIGNED_OUT, "", ""
        )

    def run_archive(command, input_text=None, timeout=None):
        if "def quit_chromium" in command:
            host.calls.append("quit chromium")
            return subprocess.CompletedProcess(command, 0, host.chromium_quit, "")
        host.calls.append("archive")
        host.archive_runs += 1
        arguments = shlex.split(command)[3:]
        # This is the fake remote's interpreter; it only owns pytest's temp home.
        return subprocess.run(
            [sys.executable, "-c", _ARCHIVE_PROGRAM, *arguments],
            input=input_text,
            text=True,
            capture_output=True,
            env={**os.environ, "HOME": str(home)},
            check=False,
        )

    host.run_command = run_command
    host._run = run_archive
    host.read_remote_text = lambda _path: json.dumps({"probes": SEALED_PROBES})
    return host


@pytest.fixture
def signed_in_home(tmp_path):
    if os.getuid() == 0:
        pytest.skip("archive requires the non-root test user")
    home, golden = tmp_path / "home", tmp_path / "golden"
    for relative in SIGN_INS:
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("sealed " + relative)
        path.chmod(0o600)
    (home / CURSOR).chmod(0o644)
    (home / ".codex/config.toml").write_text("golden config")
    (home / "settings").write_text("golden")
    captured = subprocess.run(
        [sys.executable, "-c", _ARCHIVE_PROGRAM, "capture", str(home), str(golden)],
        input="[]",
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert captured.returncode == 0, captured.stdout + captured.stderr
    for relative in SIGN_INS:
        # The harness rotated its token after the seal.
        (home / relative).write_text("live " + relative)
    (home / "settings").write_text("live")
    return home, golden


def test_capture_leaves_every_sign_in_out_of_the_golden(signed_in_home):
    _home, golden = signed_in_home
    with tarfile.open(golden / "home.tar.gz") as archive:
        names = set(archive.getnames())
    assert not names & set(SIGN_INS)
    assert ".codex/config.toml" in names


def test_reset_keeps_every_live_sign_in_without_probing_it(signed_in_home):
    home, golden = signed_in_home
    host = sealed_host(home, set())
    for _ in range(2):
        result = archive_operation(host, "reset", str(golden))
        assert result.ok, result.evidence
    for relative in SIGN_INS:
        assert (home / relative).read_text() == "live " + relative
        assert relative in result.evidence["preserved_entries"]
    assert (home / CURSOR).stat().st_mode & 0o777 == 0o644
    assert (home / CLAUDE).stat().st_mode & 0o777 == 0o600
    assert (home / ".codex/config.toml").read_text() == "golden config"
    assert (home / "settings").read_text() == "golden"
    assert host.probed == []


def test_rotated_refresh_tokens_are_never_rolled_back(signed_in_home):
    # Every harness rotates its refresh token on use, so a sealed token is dead
    # once the live one refreshes (HTTP 401 refresh_token_reused on Codex).
    home, golden = signed_in_home
    host = sealed_host(home, set())
    for rotation in (1, 2):
        for relative in SIGN_INS:
            (home / relative).write_text(f"refresh-token-{rotation} {relative}")
        result = archive_operation(host, "reset", str(golden))
        assert result.ok, result.evidence
        for relative in SIGN_INS:
            assert (
                home / relative
            ).read_text() == f"refresh-token-{rotation} {relative}"


def test_a_sign_in_an_older_golden_sealed_is_never_restored(signed_in_home):
    home, golden = signed_in_home
    sealed = golden.parent / "sealed-store"
    sealed.write_text("sealed " + CODEX)
    with tarfile.open(golden / "home.tar.gz", "r:gz") as old:
        members = [(m, old.extractfile(m).read() if m.isfile() else None) for m in old]
    with tarfile.open(golden / "home.tar.gz", "w:gz") as archive:
        for member, content in members:
            archive.addfile(member, None if content is None else io.BytesIO(content))
        archive.add(sealed, arcname=CODEX)
    manifest = json.loads((golden / "manifest.json").read_text())
    manifest["sha256"] = hashlib.sha256(
        (golden / "home.tar.gz").read_bytes()
    ).hexdigest()
    (golden / "manifest.json").write_text(json.dumps(manifest))
    (home / CODEX).unlink()
    result = archive_operation(sealed_host(home, set()), "reset", str(golden))
    assert result.ok, result.evidence
    assert not (home / CODEX).exists()


def test_symlinked_sign_in_refuses_before_clearing(signed_in_home):
    home, golden = signed_in_home
    outside = home.parent / "outside"
    (home / CLAUDE).rename(outside)
    (home / CLAUDE).symlink_to(outside)
    host = sealed_host(home, set())
    result = archive_operation(host, "reset", str(golden))
    assert host.archive_runs == 1
    assert not result.ok and result.error_code == "linux_preserved_home_entry_unsafe"
    assert (home / "settings").read_text() == "live"


def test_chromium_quits_before_capture_or_reset_touches_the_home(
    signed_in_home, tmp_path
):
    # Chromium writes its cookie store when it quits; a capture taken while it
    # runs can miss the operator's newest sign-in.
    home, golden = signed_in_home
    host = sealed_host(home, set())
    captured = archive_operation(host, "capture", str(tmp_path / "recaptured"))
    assert captured.ok, captured.evidence
    result = archive_operation(host, "reset", str(golden))
    assert result.ok, result.evidence
    assert host.calls == ["quit chromium", "archive"] * 2


def test_chromium_that_does_not_quit_refuses_before_clearing(signed_in_home):
    home, golden = signed_in_home
    host = sealed_host(home, set())
    host.chromium_quit = json.dumps(
        {
            "ok": False,
            "reason": "linux_desktop_chromium_quit_not_proved",
            "recovery": "Close Chromium.",
        }
    )
    result = archive_operation(host, "reset", str(golden))
    assert not result.ok
    assert result.error_code == SIGN_IN_APP_QUIT_NOT_PROVED
    assert result.evidence["app"] == "Chromium"
    assert result.evidence["recovery"] == "Close Chromium."
    assert host.archive_runs == 0
    assert (home / "settings").read_text() == "live"
