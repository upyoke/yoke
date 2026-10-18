"""Git checkout identity and supported native instruction layouts."""

import json
import subprocess
import tempfile
from pathlib import Path

from runtime.api.fixtures.machine_config_test import select_machine_config_file

import pytest

from yoke_cli.config import writer
from yoke_cli.project_install import instruction_discovery as instructions
from yoke_cli.project_install import runner
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.machine_config.checkout import main_checkout
from yoke_contracts.machine_config.schema_projects import project_entry_for_checkout
from yoke_core.domain.project_install_test_helpers import make_bundle


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )


@pytest.fixture
def external_lane():
    with tempfile.TemporaryDirectory(prefix="yoke-checkout-", dir="/tmp") as scratch:
        yield Path(scratch) / "lane"


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "main café"
    root.mkdir()
    _git(root, "init")
    (root / "AGENTS.md").write_text("canonical instructions\n")
    (root / "CLAUDE.md").symlink_to("AGENTS.md")
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "Initial",
    )
    return root


@pytest.mark.parametrize("placement", ["external", "nested"])
def test_git_lane_resolves_main_and_accepts_parent_canonical_link(
    checkout, tmp_path, external_lane, placement
):
    lane = external_lane if placement == "external" else checkout / ".worktrees/lane"
    _git(checkout, "worktree", "add", "-b", "lane", str(lane))
    assert main_checkout(lane) == checkout
    nested = lane / "subdirectory"
    nested.mkdir()
    assert main_checkout(nested) == checkout
    payload = {
        "active_env": "local",
        "connection_projects": {
            "local": [{"checkout": str(checkout), "project_id": 7}]
        },
    }
    assert project_entry_for_checkout(payload, nested) == {
        "project_id": 7,
    }
    instructions.assert_claude_loading(lane, settings={})
    # Only the parent's link remains; it targets the main checkout's bytes.
    (lane / "CLAUDE.md").unlink()
    instructions.assert_claude_loading(lane, settings={})


@pytest.mark.parametrize(
    "rel,token",
    [
        ("CLAUDE.md", "@AGENTS.md"),
        ("CLAUDE.local.md", "@AGENTS.md"),
        (".claude/CLAUDE.md", "@../AGENTS.md"),
    ],
)
def test_explicit_canonical_import_is_supported(tmp_path, rel, token):
    (tmp_path / "AGENTS.md").write_text("canonical\n")
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Project-specific guidance\n" + token + "\n")
    instructions.assert_claude_loading(tmp_path, settings={})


@pytest.mark.parametrize(
    "text",
    ["See AGENTS.md", "`@AGENTS.md`", "```\n@AGENTS.md\n```", "@../other/AGENTS.md"],
)
def test_prose_code_and_unrelated_import_do_not_prove_loading(tmp_path, text):
    (tmp_path / "CLAUDE.md").write_text(text)
    with pytest.raises(ProjectInstallError, match="Set Project instructions"):
        instructions.assert_claude_loading(tmp_path, settings={})


def _config(tmp_path, monkeypatch, entries):
    monkeypatch.delenv("YOKE_ENV", raising=False)
    (tmp_path / "api.token").write_text("test-token\n")
    cfg = tmp_path / "config.json"
    select_machine_config_file(monkeypatch, cfg)
    cfg.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": {
                    "prod": {
                        "transport": "https",
                        "api_url": "https://example.test",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(tmp_path / "api.token"),
                        },
                    }
                },
                "connection_projects": {"prod": entries},
            }
        )
    )
    return cfg


def test_install_from_external_lane_keeps_existing_routing(
    checkout, tmp_path, external_lane, monkeypatch
):
    lane = external_lane
    _git(checkout, "worktree", "add", "-b", "lane", str(lane))
    cfg = _config(
        tmp_path,
        monkeypatch,
        [{"checkout": str(checkout), "project_id": 7}],
    )
    before = cfg.read_bytes()
    assert runner._register_in_machine_config(lane, 7, cfg, True) is False
    assert cfg.read_bytes() == before


def test_first_install_from_external_lane_registers_main(
    checkout, tmp_path, external_lane, monkeypatch
):
    lane = external_lane
    _git(checkout, "worktree", "add", "-b", "lane", str(lane))
    cfg = _config(tmp_path, monkeypatch, [])
    assert runner._register_in_machine_config(lane, 7, cfg, True)
    assert json.loads(cfg.read_text())["connection_projects"]["prod"] == [
        {"checkout": str(checkout), "project_id": 7}
    ]


def test_install_refuses_displacing_an_unrelated_checkout(tmp_path, monkeypatch):
    original = tmp_path / "original"
    original.mkdir()
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    cfg = _config(
        tmp_path,
        monkeypatch,
        [{"checkout": str(original), "project_id": 7}],
    )
    before = cfg.read_bytes()
    with pytest.raises(
        writer.MachineConfigWriteError, match="project register --reassign"
    ):
        runner._register_in_machine_config(incoming, 7, cfg, True)
    assert cfg.read_bytes() == before


def test_bundle_report_names_only_written_discovery_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(instructions.shutil, "which", lambda _: None)
    receipt = apply_bundle(tmp_path, make_bundle(), source="test")
    assert receipt["skill_discovery_paths"] == [".claude/skills/yoke"]
    assert receipt["skill_discovery_written"] == [".claude/skills/yoke"]
    assert not (tmp_path / ".codex/skills/yoke").exists()
    assert not (tmp_path / ".cursor/skills/yoke").exists()


def test_git_identity_failure_refuses_before_routing(checkout, monkeypatch):
    from yoke_contracts.machine_config import checkout as identity
    from yoke_contracts.machine_config.schema_connections import (
        MachineConfigContractError,
    )

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr(identity.subprocess, "run", timeout)
    with pytest.raises(
        MachineConfigContractError,
        match="checkout_identity_unavailable.*repair Git access",
    ):
        main_checkout(checkout)


def test_parent_import_to_missing_main_instructions_refuses(checkout):
    lane = checkout / ".worktrees/lane"
    _git(checkout, "worktree", "add", "-b", "lane", str(lane))
    (lane / "CLAUDE.md").unlink()
    (checkout / "CLAUDE.md").unlink()
    (checkout / "CLAUDE.md").write_text("@AGENTS.md\n")
    (checkout / "AGENTS.md").unlink()
    with pytest.raises(ProjectInstallError, match="canonical_instructions_not_loaded"):
        instructions.assert_claude_loading(lane, settings={})
