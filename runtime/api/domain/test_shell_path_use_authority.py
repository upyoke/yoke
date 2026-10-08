"""Capacity inspection retains content, lane, stage, and machine boundaries."""

from contextlib import nullcontext

import pytest

from yoke_contracts.hook_runner.session_cwd import client_machine_home_fact
from yoke_core.domain import lint_session_cwd as guard
from yoke_core.domain import lint_session_cwd_validate as authority
from yoke_core.domain.lane_occupancy import LaneOccupant
from yoke_core.domain.lint_shell_path_use import PathRole, analyze_shell_path_use
from yoke_core.domain.lint_payload_path_use import extract_payload_path_uses
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree
from yoke_core.hooks.types import HookContext, Outcome
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


HOME = "/clients/operator"
ROOT = "/workspace/product"
LANE = ROOT + "/.worktrees/active"
SESSION = "historical-holder"


@pytest.fixture
def isolated_authority(monkeypatch):
    # The original capacity refusal held an implementing item and this lane.
    # Its recorded claim/lane/transition identities are retained in shell_path_use_coverage.json.
    monkeypatch.setattr(guard, "_open_conn", lambda: nullcontext(object()))
    monkeypatch.setattr(
        authority,
        "claimed_worktrees",
        lambda *_a, **_k: [
            ClaimedWorktree(1, None, LANE),
        ],
    )
    monkeypatch.setattr(authority, "_recorded_repo_roots", lambda _c: [ROOT])
    monkeypatch.setattr(authority, "occupying_claim", lambda *_a, **_k: None)
    monkeypatch.setattr(authority, "lookup_item_status", lambda *_a: "implementing")
    monkeypatch.setattr(
        authority, "lookup_item_workflow", lambda *_a: builtin_workflow_runtime("dash")
    )
    monkeypatch.setattr(authority, "is_under_yoke_control_plane", lambda _p: False)
    monkeypatch.setattr(guard, "emit_deny_and_build_audit", lambda _v: {})
    monkeypatch.setattr(guard, "emit_mismatch_allowed_read_only", lambda **_k: None)

    def unexpected_failure(**facts):
        raise AssertionError(f"Replay attempted a fail-open: {facts}")

    monkeypatch.setattr(guard, "emit_fail_open", unexpected_failure)


def evaluate(command, harness="codex"):
    payload = {
        "session_id": SESSION,
        "cwd": ROOT,
        "tool_name": "Bash",
        "tool_input": {"command": command},
        **client_machine_home_fact(HOME),
    }
    return guard.evaluate(
        HookContext(
            event_name="PreToolUse",
            executor_family=harness,
            executor_surface=harness,
            payload=payload,
            tool_name="Bash",
            session_id=SESSION,
            remote=True,
        )
    )


@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
def test_original_capacity_refusal_and_permitted_counterpart(
    isolated_authority, harness
):
    assert evaluate(f"df -k {HOME}/.yoke /tmp", harness).outcome is Outcome.NOOP
    assert evaluate(f"df -k {LANE} /tmp", harness).outcome is Outcome.NOOP


@pytest.mark.parametrize(
    "command",
    [
        f"cat {HOME}/.yoke/config-private.json",
        f"df -k {HOME}/.yoke && cat .yoke/config-private.json",
        f"df -k {HOME}/.yoke && cat ~/.yoke/config-private.json",
        f"ls {HOME}/.yoke",
        f"stat {HOME}/.yoke",
        f"file {HOME}/.yoke",
        f"du -sh {HOME}/.yoke",
        f"cd {HOME}/.yoke && df -k .",
        f"touch {HOME}/.yoke/out",
        f"df -k {HOME}/.yoke > {HOME}/.yoke/out",
        f"df -k {HOME}/.yoke && touch {HOME}/.yoke",
        f"df -k {HOME}/.yoke && touch $unknown",
        f"df -k {HOME}/.yoke/*",
        f"df -k {HOME}/.yoke && bash -c 'opaque action'",
    ],
)
def test_inspection_does_not_grant_other_access(isolated_authority, command):
    assert evaluate(command).outcome is Outcome.DENY


def test_capacity_may_have_an_independently_authorized_output(isolated_authority):
    assert evaluate(f"df -k {HOME}/.yoke > {LANE}/capacity.txt").outcome is Outcome.NOOP


def test_capacity_does_not_mutate_a_foreign_lane(isolated_authority, monkeypatch):
    foreign = ROOT + "/.worktrees/foreign"
    occupant = LaneOccupant(2, "other-holder", 2, "", foreign)
    monkeypatch.setattr(
        authority,
        "occupying_claim",
        lambda _c, *, target, **_k: occupant if target.startswith(foreign) else None,
    )
    assert evaluate(f"df -k {foreign} && touch {LANE}/out").outcome is Outcome.NOOP
    assert evaluate(f"df -k {foreign} && touch {foreign}/out").outcome is Outcome.DENY


def test_capacity_does_not_relax_pre_implementation_writes(
    isolated_authority, monkeypatch
):
    monkeypatch.setattr(authority, "lookup_item_status", lambda *_a: "idea")
    uses = extract_payload_path_uses(
        {
            "tool_name": "Bash",
            "cwd": ROOT,
            "tool_input": {"command": f"touch {LANE}/out"},
        }
    )
    verdict = authority.validate_targets(
        object(),
        session_id=SESSION,
        targets=[u.path for u in uses],
        command=f"touch {LANE}/out",
        tool_name="Bash",
        path_uses=uses,
    )
    assert not verdict.allow
    assert verdict.failure_class == "pre_implementing_status"
    assert evaluate(f"df -k {LANE}").outcome is Outcome.NOOP


def test_client_home_never_resolves_against_server_home(
    isolated_authority, monkeypatch
):
    monkeypatch.setenv("HOME", "/server/home")
    uses = extract_payload_path_uses(
        {"tool_name": "Bash", "cwd": ROOT, "tool_input": {"command": "df -k ~/.yoke"}},
        machine_home=HOME,
    )
    assert uses[0].path == HOME + "/.yoke"
    assert uses[0].role == PathRole.CAPACITY


def test_remote_metadata_keeps_local_output_authority(isolated_authority):
    command = "yoke test-machine exec --project sample --machine worker -- df -k /remote/.private"
    assert not analyze_shell_path_use(command).inspection_only
    assert evaluate(command + f" > {HOME}/.yoke/out").outcome is Outcome.DENY


def test_relative_write_after_leading_cd_uses_the_lane(isolated_authority):
    assert evaluate(f"cd {LANE} && touch out").outcome is Outcome.NOOP
    assert evaluate(f"cd {HOME}/.yoke && touch out").outcome is Outcome.DENY


def test_leading_cd_home_is_the_executing_machine(isolated_authority, monkeypatch):
    monkeypatch.setenv("HOME", "/server/home")
    uses = extract_payload_path_uses(
        {
            "tool_name": "Bash",
            "cwd": ROOT,
            "tool_input": {"command": "cd ~/.yoke && touch out"},
        },
        machine_home=HOME,
    )
    assert any(u.path == HOME + "/.yoke/out" and u.role == PathRole.WRITE for u in uses)


def test_embedded_python_write_retains_local_authority(isolated_authority):
    command = f"python3 - <<'PY'\nfrom pathlib import Path\nPath('{HOME}/.yoke/out').write_text('value')\nPY"
    assert evaluate(command).outcome is Outcome.DENY


@pytest.mark.parametrize(
    "command",
    [
        "touch ~/.yoke/out",
        "cd ~/.yoke && touch out",
        "cat ~/.yoke/private",
        "df -k ~/.yoke",
        "touch ~other/private",
    ],
)
def test_unresolved_home_never_becomes_a_lane_path(isolated_authority, command):
    payload = {
        "session_id": SESSION,
        "cwd": LANE,
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    verdict = guard.evaluate_pre_tool_use(payload, machine_home="")
    assert not verdict.allow
    assert verdict.authority_reason == "unresolved_executing_machine_home"
    assert "absolute path" in verdict.reason


def test_unresolved_cwd_home_never_becomes_a_lane_path(isolated_authority):
    verdict = guard.evaluate_pre_tool_use(
        {
            "session_id": SESSION,
            "cwd": "~/lane",
            "tool_name": "Write",
            "tool_input": {"file_path": "out"},
        },
        machine_home="",
    )
    assert not verdict.allow
    assert verdict.authority_reason == "unresolved_executing_machine_home"
