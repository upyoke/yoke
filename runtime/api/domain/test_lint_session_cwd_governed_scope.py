"""Repository scope, installed release protection, and the authority hook chain."""

from contextlib import nullcontext
from importlib import import_module

import pytest

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_core.domain import lint_lane_main_write, lint_session_cwd
from yoke_core.domain import lint_session_cwd_validate as validator
from yoke_core.domain.lane_occupancy import LaneOccupant
from yoke_core.domain.lint_payload_path_use import extract_payload_path_uses
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree
from yoke_core.hooks.types import HookContext, Next, Outcome

REPO = "/governed/project"
LANE = REPO + "/.worktrees/owned"
HOME = "/executing/home"
RELEASE = HOME + "/.local/share/uv/tools/yoke-cli-releases"
CLAIM = ClaimedWorktree(item_id=101, task_num=None, worktree_path=LANE)


@pytest.fixture(autouse=True)
def authority(monkeypatch):
    monkeypatch.setattr(validator, "claimed_worktrees", lambda *a, **k: [CLAIM])
    monkeypatch.setattr(validator, "_recorded_repo_roots", lambda _: [REPO])
    monkeypatch.setattr(validator, "occupying_claim", lambda *a, **k: None)


def validate(command):
    uses = extract_payload_path_uses(
        {"tool_name": "Bash", "tool_input": {"command": command}},
        machine_home=HOME,
    )
    return validator.validate_targets(
        None, session_id="holder", targets=[u.path for u in uses],
        tool_name="Bash", command=command, path_uses=uses, machine_home=HOME,
    )


@pytest.mark.parametrize("command", [
    f"readlink {RELEASE}/current",
    "sample 123 1 1 -file /dev/stdout",
    f"{RELEASE}/current/bin/python3 -V",
    f"ssh -i {HOME}/.ssh/key host true",
    f"rg -n validate {RELEASE}/current/lib/yoke_core/domain/guard.py",
    f"nl -ba {RELEASE}/current/lib/yoke_core/domain/guard.py",
    f"sed -n '1,30p' {RELEASE}/current/lib/yoke_core/domain/guard.py",
])
def test_external_diagnostics_pass_with_a_lane_claim(command):
    assert validate(command).allow


@pytest.mark.parametrize("target", ["/etc/passwd", HOME + "/.claude/jobs/job/result.json"])
def test_external_paths_need_no_claim(target):
    assert validate(f"touch {target}").allow


@pytest.mark.parametrize("target", [
    RELEASE + "/current/lib/yoke_core/guard.py",
    HOME + "/.codex/plugins/plugin/SKILL.md",
])
def test_installed_tree_writes_stay_protected(target):
    verdict = validate(f"touch {target}")
    assert not verdict.allow
    assert verdict.failure_class == validator.SCOPE_FAILURE_CLASS


def test_unclaimed_lane_write_still_refuses():
    verdict = validate(f"touch {REPO}/.worktrees/unclaimed/file.py")
    assert not verdict.allow
    assert verdict.failure_class == validator.SCOPE_FAILURE_CLASS


def test_foreign_lane_write_still_refuses(monkeypatch):
    occupant = LaneOccupant(7, "other", 102, "EXAMPLE-2", REPO + "/.worktrees/other")
    monkeypatch.setattr(validator, "occupying_claim", lambda *a, **k: occupant)
    verdict = validate(f"touch {occupant.lane_path}/file.py")
    assert not verdict.allow
    assert verdict.failure_class == validator.FOREIGN_LANE_FAILURE_CLASS
    assert verdict.occupant is occupant


def test_main_write_refuses_in_authority_hook_chain(monkeypatch):
    monkeypatch.setattr(lint_session_cwd, "_open_conn", lambda: nullcontext(None))
    monkeypatch.setattr(lint_lane_main_write, "_open_conn", lambda: nullcontext(None))
    monkeypatch.setattr(lint_lane_main_write, "claimed_worktrees", lambda *a, **k: [CLAIM])
    monkeypatch.setattr(lint_lane_main_write, "_lane_is_active", lambda *a: True)
    monkeypatch.setattr(lint_lane_main_write, "lane_path_exists_on_disk", lambda *a: True)
    monkeypatch.setattr(lint_lane_main_write, "item_label", lambda *a: "Example item")
    monkeypatch.setattr(lint_lane_main_write, "emit_denied", lambda **k: None)
    payload = {
        "session_id": "holder", "tool_name": "Bash", "cwd": LANE,
        "tool_input": {"command": f"touch {REPO}/source.py"},
    }
    record = HookContext("PreToolUse", "codex", "codex-cli", payload, tool_name="Bash")
    authority_modules = {lint_session_cwd.__name__, lint_lane_main_write.__name__}
    decisions = []
    for module in ordered_pipeline_for("PreToolUse", "Bash"):
        if module in authority_modules:
            decision = import_module(module).evaluate(record)
            decisions.append(decision)
            if decision.next is Next.STOP:
                break
    assert [d.outcome for d in decisions] == [Outcome.NOOP, Outcome.DENY]
    assert "main" in decisions[-1].message.lower()
