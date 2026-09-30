"""Distribution persistence and fresh-process update regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from yoke_cli.commands.adapters import self_update as update_command
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import distribution, machine_config, self_update
from yoke_cli.self_host import release_target
from yoke_contracts.install_binding import KIND_PACKAGED_WHEEL


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(path))
    return path


def test_update_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["update", "--channel", "beta"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is update_command.update
    assert remaining == ["--channel", "beta"]


def test_explicit_selection_preserves_other_machine_settings(config_file, capsys):
    config_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "settings": {"another_setting": "kept"},
            }
        )
    )
    resolved = resolve_tool_shaped(
        [
            "config",
            "distribution",
            "set",
            "--origin",
            "https://fork.example/",
            "--channel",
            "preview",
            "--json",
        ]
    )
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter(remaining) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["origin"] == "https://fork.example"
    assert machine_config.load_config()["settings"] == {
        "another_setting": "kept",
        "distribution": {"origin": "https://fork.example", "channel": "preview"},
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"settings": {}},
        {
            "settings": {"distribution": {"channel": "stable"}},
        },
    ],
)
def test_update_without_recorded_origin_refuses_before_network(
    config_file,
    monkeypatch,
    payload,
    capsys,
):
    config_file.write_text(json.dumps(payload))
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: {
            "kind": KIND_PACKAGED_WHEEL,
            "version": "1.0.0",
        },
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _: "/bin/yoke")
    monkeypatch.setattr(
        release_target, "_FETCH_BYTES", lambda _: pytest.fail("network")
    )
    assert update_command.update(["--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert "distribution_origin_missing" in error
    assert distribution.SELECT_COMMAND in error


@pytest.mark.parametrize(
    "origin,channel",
    [
        ("https://user:secret@fork.example", "stable"),
        ("https://fork.example/path", "stable"),
        ("file:///tmp/dist", "stable"),
        ("https://[invalid", "stable"),
        ("https://fork.example", "../stable"),
    ],
)
def test_invalid_selection_writes_nothing(config_file, origin, channel):
    with pytest.raises(distribution.DistributionError):
        distribution.save(origin=origin, channel=channel)
    assert not config_file.exists()


def test_fresh_process_update_uses_recorded_origin_and_channel(config_file):
    distribution.save(origin="https://fork.example", channel="preview")
    # Retain import paths, but remove all distribution environment overrides:
    # the child has no process-local state from the selection command.
    env = dict(os.environ)
    for key in ("YOKE_INSTALL_BASE_URL", "YOKE_CHANNEL", "YOKE_RELEASE_CHANNEL"):
        env.pop(key, None)
    script = """
import json
import subprocess
from yoke_cli.config import self_update
from yoke_cli.self_host import release_target
from yoke_contracts.api_urls import DISTRIBUTION_BASE_URL_ENV
import os
os.environ.pop(DISTRIBUTION_BASE_URL_ENV, None)
self_update.install_binding.detect = lambda: {"kind": "packaged-wheel", "version": "1.0.0"}
self_update.shutil.which = lambda _: "/bin/yoke"
self_update._RUN = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "1.0.1\\n", "")
seen = []
def fetch(url):
    seen.append(url)
    if url.endswith("/dist/channels/preview.json"):
        return json.dumps({"schema_version": 3, "channel": "preview", "version": "1.0.1",
            "migration_history": {"source_commit": "a" * 40},
            "installer": {"python_url": "https://fork.example/dist/install.py"}}).encode()
    assert url == "https://fork.example/dist/install.py"
    return b"import sys; assert sys.argv[sys.argv.index('--base-url')+1] == 'https://fork.example'; assert sys.argv[sys.argv.index('--channel')+1] == 'preview'"
release_target._FETCH_BYTES = fetch
print(json.dumps({"result": self_update.run_update(), "seen": seen}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["result"]["base_url"] == "https://fork.example"
    assert result["result"]["channel"] == "preview"
    assert result["result"]["new_version"] == "1.0.1"
    assert result["seen"] == [
        "https://fork.example/dist/channels/preview.json",
        "https://fork.example/dist/install.py",
    ]


def test_explicit_update_channel_keeps_recorded_origin(config_file, monkeypatch):
    distribution.save(origin="https://fork.example", channel="preview")
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: {
            "kind": KIND_PACKAGED_WHEEL,
            "version": "1.0.0",
        },
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _: "/bin/yoke")

    def resolve(**kwargs):
        assert kwargs == {"base_url": "https://fork.example", "channel": "beta"}
        raise release_target.ReleaseTargetError("stop after resolving selection")

    monkeypatch.setattr(release_target, "channel_release_target", resolve)
    with pytest.raises(self_update.SelfUpdateError, match="stop after resolving"):
        self_update.run_update(channel="beta")
