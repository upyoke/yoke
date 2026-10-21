"""Execute the real remote program against disposable harness installations."""

import json
import os
import shlex
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
        environment = {
            k: v
            for k, v in os.environ.items()
            if k not in {"CURSOR_CONFIG_DIR", "XDG_CONFIG_HOME"}
        }
        return subprocess.run(
            [sys.executable, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**environment, "HOME": str(self.home), "PATH": "/usr/bin:/bin"},
        )


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + text + "\n")
    path.chmod(0o755)
    return path


def cursor_release(home, version, text):
    channel_command = """import json, os, sys
from pathlib import Path
config = Path(os.environ['HOME']) / '.cursor/cli-config.json'
try:
    settings = json.loads(config.read_text()) if config.exists() else {}
    settings['channel'] = sys.argv[1]
except (ValueError, TypeError):
    print('repair cli-config.json', file=sys.stderr)
    raise SystemExit(1)
config.parent.mkdir(parents=True, exist_ok=True)
config.write_text(json.dumps(settings, indent=2))
"""
    vendor_command = (
        'if [ "$1" = set-channel ]; then exec '
        + shlex.quote(sys.executable)
        + " -c "
        + shlex.quote(channel_command)
        + ' "$2"; fi\n'
    )
    return executable(
        home / ".local/share/cursor-agent/versions" / version / "cursor-agent",
        vendor_command + text,
    )


@pytest.mark.parametrize("previous", [True, False])
@pytest.mark.parametrize("installer_exit", [0, 1])
def test_cursor_installer_success_requires_a_runnable_binary(
    tmp_path, monkeypatch, previous, installer_exit
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
    installer = f'ln -sf "{broken}" "$HOME/.local/bin/agent"; exit {installer_exit}'
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
        assert result.error_code == (
            "harness_cli_install_failed"
            if installer_exit
            else "harness_cli_install_unverified"
        )
        assert "cursor 2026.10.19-6bbf2c4" in result.evidence["detail"]
        assert "dyld: Symbol not found" in result.evidence["detail"]
    probe = clis.probe_harness_cli_versions(host)["cursor"]
    if previous:
        assert probe == "2026.09.01-bbbbbbb"
    else:
        assert probe["exit_code"] == 134
        assert "dyld: Symbol not found" in probe["stderr"]


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


def test_retained_cursor_survives_a_request_that_would_auto_update(
    tmp_path, monkeypatch
):
    config = tmp_path / ".cursor/cli-config.json"
    config.parent.mkdir()
    settings = {"version": 1, "channel": "lab", "model": {"id": "chosen"}}
    config.write_text(json.dumps(settings))
    broken = cursor_release(tmp_path, LATEST["cursor"], "exit 134")
    old = cursor_release(
        tmp_path,
        "2026.08.25-aaaaaaa",
        """if [ "$1" = --version ]; then echo 2026.08.25-aaaaaaa; exit; fi
if ! /usr/bin/grep -q '"channel": "static"' "$HOME/.cursor/cli-config.json"; then
  ln -sf "$HOME/.local/share/cursor-agent/versions/2026.10.19-6bbf2c4/cursor-agent" "$HOME/.local/bin/agent"
fi
echo READY""",
    )
    local_bin = tmp_path / ".local/bin"
    local_bin.mkdir(parents=True)
    (local_bin / "agent").symlink_to(old)
    monkeypatch.setitem(
        clis.HARNESS_CLI_RELEASE_BY_ID,
        "cursor",
        replace(
            clis.HARNESS_CLI_RELEASE_BY_ID["cursor"],
            install_script=f'ln -sf "{broken}" "$HOME/.local/bin/agent"',
        ),
    )
    host = LocalHost(tmp_path)
    result = clis.install_harness_clis(host, LATEST, ["cursor"])
    assert result.ok, result.evidence
    assert json.loads(config.read_text()) == {**settings, "channel": "static"}
    request = subprocess.run(
        [str(local_bin / "agent"), "-p", "Reply READY"],
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert request.stdout.strip() == "READY"
    assert clis.probe_harness_cli_versions(host)["cursor"] == "2026.08.25-aaaaaaa"


@pytest.mark.parametrize("content", ["{broken", "[1, 2]"])
def test_cursor_holdback_preserves_invalid_user_config(tmp_path, monkeypatch, content):
    config = tmp_path / ".cursor/cli-config.json"
    config.parent.mkdir()
    config.write_text(content)
    old = cursor_release(tmp_path, "2026.08.25-aaaaaaa", "echo 2026.08.25-aaaaaaa")
    broken = cursor_release(
        tmp_path, LATEST["cursor"], "echo unsupported >&2; exit 134"
    )
    local_bin = tmp_path / ".local/bin"
    local_bin.mkdir(parents=True)
    (local_bin / "agent").symlink_to(old)
    monkeypatch.setitem(
        clis.HARNESS_CLI_RELEASE_BY_ID,
        "cursor",
        replace(
            clis.HARNESS_CLI_RELEASE_BY_ID["cursor"],
            install_script=f'ln -sf "{broken}" "$HOME/.local/bin/agent"',
        ),
    )
    result = clis.install_harness_clis(LocalHost(tmp_path), LATEST, ["cursor"])
    assert not result.ok
    assert config.read_text() == content
    assert "repair cli-config.json" in result.evidence["recovery"]
    assert "unsupported" in result.evidence["detail"]
