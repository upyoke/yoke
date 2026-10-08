"""Operand-role regressions minimized from retained native tool calls."""

import json
import shlex
from pathlib import Path

import pytest

from yoke_core.domain.lint_shell_path_use import PathRole, analyze_shell_path_use
from yoke_core.domain.lint_payload_path_use import extract_payload_path_uses


CASES = json.loads(
    (Path(__file__).parent / "fixtures/shell_path_use_calls.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["tool_call_id"]))
def test_actual_operand_relationships(case):
    analysis = analyze_shell_path_use(case["command"])
    for role, operand in case["expected_uses"]:
        assert (operand, PathRole(role)) in [
            (use.path, use.role) for use in analysis.uses
        ]
    if "direct_write" in case:
        assert analysis.direct_write == case["direct_write"]
    assert analysis.inspection_only == case["inspection_only"]
    assert set(analysis.write_targets) == set(case["write_targets"])


@pytest.mark.parametrize(
    "target",
    [
        "/clients/operator/.yoke",
        "/clients/operator/.yoke/../.yoke",
        "/clients/operator/.private directory",
    ],
)
def test_quoting_and_normalization_preserve_capacity_role(target):
    payload = {
        "tool_name": "Bash",
        "cwd": "/workspace/product",
        "tool_input": {
            "command": f"df -k {shlex.quote(target)} /tmp",
        },
    }
    uses = extract_payload_path_uses(payload, machine_home="/clients/operator")
    assert all(use.role == PathRole.CAPACITY for use in uses)
    assert uses[0].path == target


@pytest.mark.parametrize(
    "tail",
    [
        "touch /clients/operator/.yoke",
        "> /clients/operator/.yoke/out",
        "touch $unresolved",
        "bash -c 'opaque action'",
        "unknown /clients/operator/.yoke",
    ],
)
def test_adding_a_mutation_or_unknown_shape_never_inherits_inspection(tail):
    separator = " " if tail.startswith(">") else " && "
    result = analyze_shell_path_use("df -k /clients/operator/.yoke" + separator + tail)
    assert not result.inspection_only
    if tail.startswith("touch $") or tail.startswith(("bash", "unknown")):
        assert not any(use.role == PathRole.CAPACITY for use in result.uses)
    else:
        assert any(use.role == PathRole.WRITE for use in result.uses)


@pytest.mark.parametrize("redirect", ["> /local/out", ">/local/out", "2> /local/out"])
def test_remote_argv_never_hides_a_local_redirect(redirect):
    result = analyze_shell_path_use(
        "yoke test-machine exec --project sample --machine worker -- /bin/ls /Applications "
        + redirect
    )
    assert "/Applications" not in result.local_targets
    assert "/local/out" in result.write_targets
    assert any(use.role == PathRole.REMOTE for use in result.uses)


@pytest.mark.parametrize(
    "command",
    [
        "df --sync /clients/operator/.yoke",
        "df --unknown /clients/operator/.yoke",
        "df -k /clients/operator/.yoke < /clients/operator/.private",
        "df -k /clients/operator/.yoke $(opaque)",
    ],
)
def test_unknown_or_content_access_is_not_capacity_inspection(command):
    result = analyze_shell_path_use(command)
    assert not result.inspection_only
    assert not any(use.role == PathRole.CAPACITY for use in result.uses)


@pytest.mark.parametrize(
    "command",
    [
        "rm /workspace/product/file",
        "rmdir /workspace/product/dir",
        "sed -i '' 's/a/b/' /workspace/product/file",
        "git -C /workspace/product checkout main",
    ],
)
def test_state_moves_are_mutations_for_every_authority_consumer(command):
    from yoke_core.domain.lint_lane_main_write_classify import is_write_operation
    from yoke_core.domain.lint_session_cwd_foreign_lane import is_lane_mutation

    assert analyze_shell_path_use(command).mutation
    assert is_lane_mutation("Bash", command)
    assert is_write_operation("Bash", {"tool_input": {"command": command}})
