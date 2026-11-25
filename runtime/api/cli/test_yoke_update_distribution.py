"""Distribution persistence and fresh-process update regressions."""

from __future__ import annotations

from yoke_contracts import distribution_target
import json
import os
import subprocess
import sys

import pytest

from yoke_cli.commands.adapters import self_update as update_command
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_contracts.machine_config import distribution, reader as machine_config
from yoke_contracts.machine_config.runtime import machine_id
from yoke_contracts.owner_private_path import write_owner_private
from yoke_cli.config import distribution_write, self_update, writer
from yoke_cli.self_host import release_target
from yoke_contracts.install_binding import KIND_PACKAGED_WHEEL

from runtime.api.fixtures.machine_config_test import select_machine_config_file


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    select_machine_config_file(monkeypatch, str(path))
    return path


def test_update_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["update", "--channel", "beta"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is update_command.update
    assert remaining == ["--channel", "beta"]


def test_installer_distribution_setting_does_not_create_a_machine_id(config_file, capsys):
    resolved = resolve_tool_shaped(
        [
            "settings", "set", "distribution",
            '{"origin":"https://fork.example","channel":"preview"}', "--json",
        ]
    )
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter(remaining) == 0
    assert json.loads(capsys.readouterr().out)["success"] is True
    assert machine_config.load_config()["settings"]["distribution"]["channel"] == "preview"
    assert "machine_id" not in json.loads(config_file.read_text())


@pytest.mark.parametrize("legacy_without_id", [False, True])
def test_distribution_and_last_connection_preserve_identity_state(
    monkeypatch, tmp_path, legacy_without_id
):
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config_file = home / "config.json"
    distribution_write.save(origin="https://fork.example", channel="preview")
    assert machine_id() is None
    token = tmp_path / "stage.token"
    token.write_text("stage-token\n")
    writer.set_connection(
        "stage", transport="https", api_url="https://api.example", token_file=str(token)
    )
    identity = machine_id()
    assert identity is not None
    if legacy_without_id:
        payload = json.loads(config_file.read_text())
        del payload["machine_id"]
        write_owner_private(config_file, json.dumps(payload))
        identity = None

    report = writer.remove_connection("stage")
    assert report.get("machine_record_kept") == identity
    payload = json.loads(config_file.read_text())
    assert not payload["connections"]
    assert not payload.get("active_env")
    assert payload.get("machine_id") == identity

    distribution_write.save(origin="https://fork.example", channel="stable")
    assert machine_id() == identity


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
            "settings",
            "set",
            "distribution",
            '{"origin":"https://fork.example/","channel":"preview"}',
            "--json",
        ]
    )
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter(remaining) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["success"] is True
    assert result["result"]["value"]["origin"] == "https://fork.example"
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
            "version": "0.2.0.202610140941",
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
        distribution_write.save(origin=origin, channel=channel)
    assert not config_file.exists()


def test_fresh_process_update_uses_recorded_origin_and_channel(config_file):
    distribution_write.save(origin="https://fork.example", channel="preview")
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
self_update.install_binding.detect = lambda: {"kind": "packaged-wheel", "version": "0.2.0.202610140941"}
self_update.shutil.which = lambda _: "/bin/yoke"
self_update._RUN = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "0.2.0.202610140942\\n", "")
seen = []
def fetch(url):
    seen.append(url)
    if url.endswith("/dist/channels/preview.json"):
        return json.dumps({"schema_version": 3, "channel": "preview", "version": "0.2.0.202610140942",
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
    assert result["result"]["new_version"] == "0.2.0.202610140942"
    assert result["seen"] == [
        "https://fork.example/dist/channels/preview.json",
        "https://fork.example/dist/install.py",
    ]


def test_explicit_update_channel_keeps_recorded_origin(config_file, monkeypatch):
    distribution_write.save(origin="https://fork.example", channel="preview")
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: {
            "kind": KIND_PACKAGED_WHEEL,
            "version": "0.2.0.202610140941",
        },
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _: "/bin/yoke")

    def resolve(**kwargs):
        assert kwargs == {"base_url": "https://fork.example", "channel": "beta"}
        raise distribution_target.ReleaseTargetError("stop after resolving selection")

    monkeypatch.setattr(release_target, "channel_release_target", resolve)
    with pytest.raises(self_update.SelfUpdateError, match="stop after resolving"):
        self_update.run_update(channel="beta")
