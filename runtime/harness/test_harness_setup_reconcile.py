"""Late native installs converge existing checkouts without creating absent homes."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_harness import harness_setup_reconcile as setup
from yoke_harness import session_relay_harness_reconcile as relay


@pytest.fixture
def machine(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    from yoke_contracts.harness_machine_hooks import HarnessMachineHooks

    monkeypatch.setattr(
        HarnessMachineHooks,
        "home_path",
        lambda self, environ=None: (
            home
            / (
                ".codex"
                if self.harness_id == "codex"
                else ".claude"
                if self.harness_id == "claude-code"
                else ".cursor"
            )
        ),
    )
    root = tmp_path / "checkout"
    lanes = [tmp_path / "lane-a", tmp_path / "lane-b"]
    hooks = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "yoke hook evaluate Stop"}]}
            ]
        }
    }
    for target in [root, *lanes]:
        (target / ".codex").mkdir(parents=True)
        (target / ".codex/hooks.json").write_text(json.dumps(hooks))
    monkeypatch.setattr(setup, "all_registered_checkouts", lambda **kw: [root])
    monkeypatch.setattr(setup, "main_checkout", lambda path: root)
    monkeypatch.setattr(setup, "registered_worktree_paths", lambda path: [root, *lanes])
    return home, root, lanes


@pytest.mark.parametrize(
    "harness,dirname",
    [("codex", ".codex"), ("claude-code", ".claude"), ("cursor", ".cursor")],
)
def test_harness_installed_after_yoke_converges_existing_lanes(
    machine, harness, dirname
):
    home, root, lanes = machine
    before = setup.reconcile_harness_setup()
    assert all(row.outcome == "skipped_no_home" for row in before.rows)
    assert not any(home.iterdir())
    (home / dirname).mkdir()
    state = relay.reconcile_on_change(path=home / "relay.json", now=100)
    assert state["fingerprint"] == [harness]
    assert state["failure"] is None
    inspected = setup.inspect_harness_setup()
    rows = [row for row in inspected.rows if row.harness_id == harness]
    assert all(row.outcome == "already_set" for row in rows), rows
    assert {row.target_path for row in rows if row.facet == "folder_trust"} == {
        str(root),
        *map(str, lanes),
    }
    files = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    again = setup.reconcile_harness_setup()
    assert all(row.outcome in ("already_set", "skipped_no_home") for row in again.rows)
    assert files == {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}


def test_modified_lane_hooks_refuse_without_minting(machine):
    home, root, lanes = machine
    (home / ".codex").mkdir()
    assert not setup.reconcile_harness_setup().failed
    hooks = lanes[0] / ".codex/hooks.json"
    hooks.write_text(hooks.read_text().replace("Stop", "SessionStart"))
    result = setup.reconcile_harness_setup(paths=[lanes[0]])
    row = next(
        r for r in result.rows if r.harness_id == "codex" and r.facet == "hook_trust"
    )
    assert row.outcome == "refused"
    assert "differs" in row.detail
    assert "re-trust in Codex" in row.recovery


@pytest.mark.parametrize(
    "harness,dirname",
    [
        ("codex", ".codex"),
        ("claude-code", ".claude"),
        ("cursor", ".cursor"),
    ],
)
def test_reconcile_repairs_a_changed_permission_mode(machine, harness, dirname):
    from yoke_contracts import harness_unattended_posture as posture

    home, _root, _lanes = machine
    (home / dirname).mkdir()
    assert not setup.reconcile_harness_setup().failed
    target = (
        posture.claude_settings_path()
        if harness == "claude-code"
        else posture.managed_config_paths()[harness]
    )
    if harness == "codex":
        target.write_text(target.read_text().replace('"never"', '"on-request"'))
    else:
        data = json.loads(target.read_text())
        if harness == "claude-code":
            data["permissions"]["defaultMode"] = "plan"
        else:
            data["approvalMode"] = "allowlist"
        target.write_text(json.dumps(data))
    result = setup.reconcile_harness_setup()
    row = next(
        r for r in result.rows if r.harness_id == harness and r.facet == "posture"
    )
    assert row.outcome == "written", row
    assert setup.posture_findings(harness) == ()


def test_malformed_file_preserved_and_other_harnesses_continue(machine):
    home, root, _ = machine
    (home / ".codex").mkdir()
    (home / ".cursor").mkdir()
    config = home / ".codex/config.toml"
    config.write_text("[invalid")
    result = setup.reconcile_harness_setup()
    assert result.failed
    assert config.read_text() == "[invalid"
    assert any(r.harness_id == "cursor" and r.outcome == "written" for r in result.rows)
    assert all(r.recovery for r in result.rows if r.outcome in setup.FAILURES)
    assert all(
        "doctor run --only harness-setup --fix" in r.recovery
        for r in result.rows
        if r.outcome == "failed"
    )


def test_inspection_never_writes_and_scoped_call_targets_only_lane(machine):
    home, root, lanes = machine
    (home / ".codex").mkdir()
    assert setup.inspect_harness_setup().failed
    assert not (home / ".codex/config.toml").exists()
    assert not setup.reconcile_harness_setup(paths=[root]).failed
    result = setup.reconcile_harness_setup(paths=[lanes[1]])
    assert not result.failed
    assert {
        r.target_path
        for r in result.rows
        if r.facet == "folder_trust" and r.harness_id == "codex"
    } == {str(lanes[1])}
    assert str(lanes[0]) not in (home / ".codex/config.toml").read_text()


def test_unwritable_facet_does_not_stop_other_facets(machine, monkeypatch):
    home, _, _ = machine
    (home / ".cursor").mkdir()
    monkeypatch.setattr(
        setup,
        "grant_folder_trust",
        lambda *a, **kw: (_ for _ in ()).throw(PermissionError("folder.json")),
    )
    result = setup.reconcile_harness_setup()
    assert any(r.outcome == "failed" and "folder.json" in r.detail for r in result.rows)
    assert any(
        r.facet == "machine_hooks" and r.outcome == "written" for r in result.rows
    )


def test_primary_identity_survives_filtering_missing_worktrees(monkeypatch, tmp_path):
    from yoke_contracts.machine_config import checkout

    missing = tmp_path / "missing-primary"
    lane = tmp_path / "existing-lane"
    lane.mkdir()
    (lane / ".git").write_text("fixture")
    output = f"worktree {missing}\0\0worktree {lane}\0\0"
    monkeypatch.setattr(
        checkout.terminal_detached_process,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=output),
    )
    assert checkout.main_checkout(lane) == missing
    assert checkout.registered_worktree_paths(lane) == [lane]


def test_machine_inventory_reconciles_every_registered_checkout(
    machine, monkeypatch, tmp_path
):
    home, root, _ = machine
    other = tmp_path / "other-checkout"
    other.mkdir()
    (home / ".cursor").mkdir()
    monkeypatch.setattr(setup, "all_registered_checkouts", lambda **kw: [root, other])
    monkeypatch.setattr(setup, "main_checkout", lambda path: path)
    monkeypatch.setattr(setup, "registered_worktree_paths", lambda path: [path])
    result = setup.reconcile_harness_setup()
    assert not result.failed
    rows = [
        r for r in result.rows if r.harness_id == "cursor" and r.facet == "folder_trust"
    ]
    assert {r.target_path for r in rows} == {str(root), str(other)}
    assert all(r.outcome == "written" for r in rows)


def test_global_skill_converges_for_each_installed_harness(machine, monkeypatch):
    home, _root, _lanes = machine
    from yoke_contracts import global_skill_install

    monkeypatch.setattr(global_skill_install, "user_home", lambda environ=None: home)
    (home / ".claude").mkdir()

    first = setup.reconcile_harness_setup(paths=[])
    outcomes = {
        r.harness_id: r.outcome for r in first.rows if r.facet == "global_skill"
    }

    assert outcomes == {
        "claude-code": "written",
        "codex": "skipped_no_home",
        "cursor": "skipped_no_home",
    }
    assert (home / ".claude/skills/yoke-global/SKILL.md").is_file()
    again = setup.inspect_harness_setup(paths=[])
    assert [
        r.outcome
        for r in again.rows
        if r.facet == "global_skill" and r.harness_id == "claude-code"
    ] == ["already_set"]
