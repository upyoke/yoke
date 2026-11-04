"""Guard regression pairs: harmless inspection and actual unauthorized writes."""

import shlex

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import seed_item, seed_item_claim
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write, lint_session_cwd
from yoke_core.domain.lint_no_agent_runtime_api_import_from_c import evaluate_payload
from yoke_core.domain.lint_session_cwd_target_extract import (
    resolve_shell_write_operands,
)


@pytest.fixture
def lanes(tmp_path):
    with test_database() as conn:
        main = tmp_path / "repo"
        (main / ".worktrees").mkdir(parents=True)
        register_machine_checkout(tmp_path / "machine-config", main, project_id=1)
        paths = []
        for item, session in [(2014, "caller"), (2015, "holder")]:
            seed_item(
                conn,
                item_id=item,
                branch=f"YOK-{item}",
                status="implementing",
                repo_path=main,
            )
            seed_item_claim(conn, session, item_id=item)
            lane = main / ".worktrees" / f"YOK-{item}"
            lane.mkdir()
            paths.append(lane)
        yield main, *paths


def verdict(guard, command, cwd):
    return guard.evaluate_pre_tool_use(
        {
            "session_id": "caller",
            "tool_name": "Bash",
            "cwd": str(cwd),
            "tool_input": {"command": command},
        }
    )


@pytest.mark.parametrize(
    "verb, allowed", [("fetch origin abc123", True), ("pull", False)]
)
def test_main_git_state(lanes, verb, allowed):
    main, own, _ = lanes
    result = verdict(lint_lane_main_write, f"git -C {main} {verb}", own)
    assert result.allow is allowed
    if not allowed:
        assert "source write to the main checkout" in result.reason


@pytest.mark.parametrize(
    "command, allowed",
    [
        (
            "yoke items section get YOK-1 --section Spec && git -C {other} diff HEAD~1 -- f",
            True,
        ),
        ("cd {other} && yoke dev run -- touch x", False),
        ("yoke items get YOK-1 && touch {other}/x", False),
        ("yoke dev run --lane {other} -- touch x && git -C {other} diff", False),
    ],
)
def test_foreign_lane_compounds(lanes, command, allowed):
    _, own, other = lanes
    result = verdict(lint_session_cwd, command.format(other=other), own)
    assert result.allow is allowed
    if not allowed:
        assert "worktree lane held by another session" in result.reason


@pytest.mark.parametrize(
    "body",
    [
        'print("line 4: from yoke_core.domain.x import y")',
        '# from yoke_core.api import service_client\nprint("ok")',
        "import yoke_cli; print(yoke_cli.__file__)",
        "import yoke_cli as cli; print(cli.__version__, cli.__path__)",
    ],
)
def test_import_text_and_module_metadata(body):
    assert (
        evaluate_payload(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "python3 -c " + shlex.quote(body),
                },
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "body, matched",
    [
        (
            "from yoke_core.api import service_client; service_client.delete_item(1)",
            "from yoke_core.api import service_client",
        ),
        ('exec("x=1; from yoke_core.api import x")', "from yoke_core.api import"),
        ("import yoke_cli; print(yoke_cli)", "import yoke_cli"),
        ("import yoke_cli as cli; cli.delete_item(1)", "import yoke_cli"),
        ("import os, yoke_cli; print(yoke_cli)", "import os, yoke_cli"),
    ],
)
def test_actual_runtime_imports(body, matched):
    result = evaluate_payload(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 -c " + shlex.quote(body),
            },
        }
    )
    assert result is not None
    assert result[1] == "denied"
    assert matched in result[0]


@pytest.mark.parametrize(
    "receiver, allowed",
    [
        ('Path("/tmp/qa-diag")', True),
        ('Path("{main}")', False),
        ('Path(os.environ["X"])', False),
    ],
)
def test_joinpath_writes(lanes, receiver, allowed):
    main, _, _ = lanes
    command = (
        "python3 - <<'PY'\nfrom pathlib import Path\nimport os\n"
        f"p = {receiver.format(main=main)}\n"
        'p.joinpath("nested", "out.json").write_text("{}")\nPY'
    )
    result = verdict(lint_lane_main_write, command, main)
    assert result.allow is allowed
    if not allowed:
        assert "BLOCKED" in result.reason


@pytest.mark.parametrize(
    "options",
    [
        "mkdir -m 700",
        "mkdir --mode 700",
        "touch -d DATE",
        "touch -t STAMP",
        "touch -r /tmp/reference",
        "truncate -s SIZE",
        "truncate -r /tmp/reference",
    ],
)
def test_write_options_are_data(lanes, options):
    main, _, _ = lanes
    assert verdict(lint_lane_main_write, f"{options} /tmp/x", main).allow is True
    result = verdict(lint_lane_main_write, f"{options} {main}/d", main)
    assert result.allow is False
    assert "source write to the main checkout" in result.reason
    targets, unresolved = resolve_shell_write_operands(f"{options} /tmp/x")
    assert targets == ["/tmp/x"]
    assert unresolved is False


@pytest.mark.parametrize("command", ["cp", "mv", "install"])
def test_target_directory_option_keeps_write_target(command):
    from yoke_core.domain.lint_shell_path_use import analyze_shell_path_use

    assert (
        "/repo/d"
        in analyze_shell_path_use(f"{command} -t /repo/d /tmp/source").write_targets
    )


def test_joinpath_without_components():
    from yoke_core.domain.lint_python_write_target_extract import (
        analyze_python_heredoc_writes,
    )

    result = analyze_python_heredoc_writes(
        "python3 - <<'PY'\nfrom pathlib import Path\n"
        "Path('/tmp/out').joinpath().write_text('x')\nPY"
    )
    assert result.targets == ["/tmp/out"]
    assert not result.unresolved_writes
