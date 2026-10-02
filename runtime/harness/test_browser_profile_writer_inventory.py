"""macOS profile snapshots refuse live writers and incomplete inventories."""

import json
import os
import subprocess
import sys

import pytest

from yoke_harness.browser_profile_writer_inventory import WRITER_INVENTORY_PROGRAM


@pytest.mark.parametrize(
    "command,file_output,file_status,file_error,reason",
    [
        (
            "chromium --user-data-dir=PROFILE",
            "",
            1,
            "",
            "browser_profile_writer_active",
        ),
        ("unrelated", "p123\n", 0, "", "browser_profile_writer_active"),
        (
            "unrelated",
            "",
            1,
            "permission denied",
            "browser_profile_writer_inventory_unavailable",
        ),
        ("unrelated", "", 2, "", "browser_profile_writer_inventory_unavailable"),
        ("unrelated", "", 1, "", None),
    ],
)
def test_macos_inventory_requires_commands_and_descriptors_clear(
    tmp_path, monkeypatch, capsys, command, file_output, file_status, file_error, reason
):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        sys, "argv", ["inventory", str(os.getuid()), str(profile), "102"]
    )
    seen = []

    def run(argv, **options):
        seen.append(argv)
        if argv[0] == "/bin/ps":
            return subprocess.CompletedProcess(
                argv, 0, "101 " + command.replace("PROFILE", str(profile)), ""
            )
        assert argv[0] == "/usr/sbin/lsof"
        assert "sudo" not in argv
        return subprocess.CompletedProcess(argv, file_status, file_output, file_error)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as outcome:
        exec(compile(WRITER_INVENTORY_PROGRAM, "writer-inventory", "exec"), {})
    assert outcome.value.code == (64 if reason else 0)
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == ({"ok": False, "reason": reason} if reason else {"ok": True})
    assert seen[0][0] == "/bin/ps"
