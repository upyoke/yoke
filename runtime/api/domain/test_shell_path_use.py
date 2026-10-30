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
        "yoke test-machine exec --project sample --test-machine worker -- /bin/ls /Applications "
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


@pytest.mark.parametrize(
    ("command", "targets"),
    [
        ("gh api /orgs/x/installations --jq .", []),
        ("gh api -X POST /repos/x/y --input /etc/passwd", ["/etc/passwd"]),
        ("gh api /x -F body=@/tmp/f", ["/tmp/f"]),
        ("gh api --field body=@relative.txt /x", ["relative.txt"]),
        ("gh api --field=body=@/tmp/f /x", ["/tmp/f"]),
        ("gh api -Fbody=@/tmp/f /x", ["/tmp/f"]),
        ("gh api --input=relative.json /x", ["relative.json"]),
        ("gh api /x --raw-field body=@/tmp/literal", []),
        ("gh api /x --input - --field body=@-", []),
        ("gh api /x > /tmp/out", ["/tmp/out"]),
        ("gh api > /tmp/out /x", ["/tmp/out"]),
        ("gh repo clone /tmp/repo", ["/tmp/repo"]),
    ],
)
def test_github_api_routes_and_local_file_operands(command, targets):
    result = analyze_shell_path_use(command)
    assert list(result.local_targets) == targets
    payload = {"tool_name": "Bash", "cwd": "/", "tool_input": {"command": command}}
    assert {use.path for use in extract_payload_path_uses(payload)} == {
        str(Path("/", target)) for target in targets
    }


@pytest.mark.parametrize(
    "flag",
    [
        "-X", "--method", "-H", "--header", "-f", "--raw-field",
        "-F", "--field", "-q", "--jq", "-t", "--template",
        "-p", "--preview", "--hostname", "--cache",
    ],
)
@pytest.mark.parametrize("equals", [False, True])
def test_github_api_option_values_before_routes_are_data(flag, equals):
    option = flag + ("=" if equals else " ") + "/value"
    result = analyze_shell_path_use(f"gh api {option} /route --input /tmp/input")
    assert list(result.local_targets) == ["/tmp/input"]
