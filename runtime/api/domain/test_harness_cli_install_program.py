"""Execute the real remote program against disposable harness installations."""

import os
import subprocess
import sys
from dataclasses import replace

import pytest

from yoke_harness import golden_harness_clis as clis

LATEST = {"claude-code": "2.1.300", "codex": "0.163.0", "cursor": "2026.10.19-6bbf2c4"}


class LocalHost:
    def __init__(self, home):
        self.home = home

    def run_command(self, argv, timeout, **context):
        return subprocess.run(
            [sys.executable, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "HOME": str(self.home), "PATH": "/usr/bin:/bin"},
        )


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + text + "\n")
    path.chmod(0o755)
    return path


def cursor_release(home, version, text):
    return executable(
        home / ".local/share/cursor-agent/versions" / version / "cursor-agent", text
    )


@pytest.mark.parametrize("previous", [True, False])
def test_cursor_installer_success_requires_a_runnable_binary(
    tmp_path, monkeypatch, previous
):
    local_bin = tmp_path / ".local/bin"
    local_bin.mkdir(parents=True)
    if previous:
        old = cursor_release(tmp_path, "2026.08.25-aaaaaaa", "echo 2026.08.25-aaaaaaa")
        (local_bin / "agent").symlink_to(old)
        # The newest runnable retained release wins, even if it was not linked.
        cursor_release(tmp_path, "2026.09.01-bbbbbbb", "echo 2026.09.01-bbbbbbb")
    broken = cursor_release(
        tmp_path,
        LATEST["cursor"],
        "echo 'dyld: Symbol not found: libc++' >&2; exit 134",
    )
    installer = f'ln -sf "{broken}" "$HOME/.local/bin/agent"'
    monkeypatch.setitem(
        clis.HARNESS_CLI_RELEASE_BY_ID,
        "cursor",
        replace(clis.HARNESS_CLI_RELEASE_BY_ID["cursor"], install_script=installer),
    )
    host = LocalHost(tmp_path)
    result = clis.install_harness_clis(host, LATEST, ["cursor"])
    assert result.ok is previous, result.evidence
    if previous:
        assert result.evidence["harness_cli_versions"]["cursor"] == "2026.09.01-bbbbbbb"
        assert "held back: cursor 2026.10.19-6bbf2c4" in result.evidence["held_back"][0]
        assert "dyld: Symbol not found" in result.evidence["held_back"][0]
        assert (local_bin / "agent").resolve() == (local_bin / "cursor-agent").resolve()
    else:
        assert result.error_code == "harness_cli_install_unverified"
        assert "cursor 2026.10.19-6bbf2c4 exit 134" in result.evidence["detail"]
        assert "dyld: Symbol not found" in result.evidence["detail"]
    probe = clis.probe_harness_cli_versions(host)["cursor"]
    assert probe["exit_code"] == (0 if previous else 134)


@pytest.mark.parametrize(
    "harness,name,old",
    [("codex", "codex", "0.149.1"), ("claude-code", "claude", "2.1.200")],
)
def test_native_cli_overwrite_restores_the_previous_runnable_executable(
    tmp_path, monkeypatch, harness, name, old
):
    executable(tmp_path / ".local/bin" / name, f"echo {old}")
    installer = f"printf '#!/bin/sh\\necho incompatible >&2; exit 1\\n' > \"$HOME/.local/bin/{name}\""
    monkeypatch.setitem(
        clis.HARNESS_CLI_RELEASE_BY_ID,
        harness,
        replace(clis.HARNESS_CLI_RELEASE_BY_ID[harness], install_script=installer),
    )
    result = clis.install_harness_clis(LocalHost(tmp_path), LATEST, [harness])
    assert result.ok, result.evidence
    assert result.evidence["harness_cli_versions"][harness] == old
    assert "incompatible" in result.evidence["held_back"][0]
