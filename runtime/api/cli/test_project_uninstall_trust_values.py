"""Project uninstall counts a harness entry as trust only when it grants trust."""

import json
from pathlib import Path

from runtime.api.cli import test_project_uninstall_owned_cleanup as owned_cleanup
from yoke_contracts import harness_folder_trust as trust
from yoke_contracts.codex_config_posture import parse_config
from yoke_cli.project_install.uninstall import uninstall

installed = owned_cleanup.installed
read_json = owned_cleanup.read_json


def _add_claude_entries(entries):
    target = trust.claude_state_path()
    payload = read_json(target)
    payload["projects"].update(entries)
    target.write_text(json.dumps(payload))


def test_entries_without_granted_trust_leave_uninstall_complete(installed):
    root, _, config = installed
    alias = root.parent / "alias"
    alias.symlink_to(root, target_is_directory=True)
    seen_only = {
        str(root.parent): {},
        str(alias): {"hasTrustDialogAccepted": False, "allowedTools": []},
    }
    _add_claude_entries(seen_only)
    codex = Path.home() / ".codex/config.toml"
    codex.write_text(
        codex.read_text()
        + f'\n[projects.{json.dumps(str(root.parent))}]\ntrust_level = "untrusted"\n'
    )
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "complete", report
    reasons = {row["reason"] for row in report["local_cleanup"]["trust"]}
    assert reasons == {"owned_exact_entry"}
    projects = read_json(trust.claude_state_path())["projects"]
    assert str(root) not in projects
    assert {key: projects[key] for key in seen_only} == seen_only
    codex_projects = parse_config(codex.read_text())["projects"]
    assert str(root) not in codex_projects
    assert codex_projects[str(root.parent)] == {"trust_level": "untrusted"}
    assert not trust.cursor_trust_file(root).exists()


def test_unrecorded_granted_trust_is_left_alone_and_unreported(installed):
    root, _, config = installed
    alias = root.parent / "alias"
    alias.symlink_to(root, target_is_directory=True)
    _add_claude_entries({str(alias): {"hasTrustDialogAccepted": True}})
    codex = Path.home() / ".codex/config.toml"
    codex.write_text(
        codex.read_text()
        + f'\n[projects.{json.dumps(str(alias))}]\ntrust_level = "trusted"\n'
    )
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "complete", report
    reasons = {row["reason"] for row in report["local_cleanup"]["trust"]}
    assert reasons == {"owned_exact_entry"}
    projects = read_json(trust.claude_state_path())["projects"]
    assert projects[str(alias)] == {"hasTrustDialogAccepted": True}
    assert str(root) not in projects
    codex_projects = parse_config(codex.read_text())["projects"]
    assert codex_projects[str(alias)] == {"trust_level": "trusted"}
    assert str(root) not in codex_projects


def test_later_harness_home_keeps_unrecorded_trust(installed, monkeypatch):
    root, _, config = installed
    later = Path.home() / "later-codex"
    later.mkdir()
    target = later / "config.toml"
    content = f'[projects.{json.dumps(str(root))}]\ntrust_level = "trusted"\n'
    target.write_text(content)
    monkeypatch.setenv("CODEX_HOME", str(later))
    report = uninstall(root, config_path=config)
    assert target.read_text() == content
    assert report["outcome"] == "complete", report
    assert all(
        row["status"] != "preserved" for row in report["local_cleanup"]["trust"]
    )
