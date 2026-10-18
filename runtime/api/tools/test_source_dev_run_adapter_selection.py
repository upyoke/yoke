"""Check adapters bind both the interpreter and child command to a selected lane."""

import pytest

from yoke_cli.commands.adapters import source_dev_run as adapter
from yoke_core.domain.verification_tree_binding import ClaimLookup
from yoke_core.tools import source_dev_run as runner


@pytest.fixture
def claimed_lanes(monkeypatch, tmp_path):
    lanes = [tmp_path / "first-source", tmp_path / "second source"]
    for lane in lanes:
        (lane / "packages/yoke-core/src/yoke_core").mkdir(parents=True)
        (lane / "pyproject.toml").touch()
    monkeypatch.setattr(
        runner.verification_tree_binding, "ambient_session_id", lambda: "session"
    )
    monkeypatch.setattr(
        runner.verification_tree_binding,
        "resolve_claim_worktrees",
        lambda _session: ClaimLookup(worktrees=tuple(map(str, lanes)), reachable=True),
    )
    monkeypatch.setattr(adapter, "_source_runner", lambda: runner)
    return lanes


@pytest.mark.parametrize(
    "command,arguments",
    [
        ("ruff_changed", ["--base", "main", "--fix-format"]),
        (
            "import_check",
            ["yoke_cli.commands.adapters.source_dev_run", "yoke_contracts"],
        ),
    ],
)
@pytest.mark.parametrize("selector", ["--lane", "--workdir"])
@pytest.mark.parametrize("equals", [False, True])
def test_check_selects_named_lane(
    monkeypatch, claimed_lanes, command, arguments, selector, equals
):
    selected = claimed_lanes[1]
    calls = []
    monkeypatch.setattr(
        runner,
        "_run_bound",
        lambda args, root, project, signature, env: calls.append((args, root)) or 7,
    )
    selection = [f"{selector}={selected}"] if equals else [selector, str(selected)]
    assert getattr(adapter, command)([*arguments, *selection]) == 7
    assert calls == [
        (["python3", "-m", f"yoke_core.tools.{command}", *arguments], selected)
    ]


@pytest.mark.parametrize("command", ["ruff_changed", "import_check"])
def test_check_refuses_ambiguous_lane(claimed_lanes, command, capsys):
    assert getattr(adapter, command)([]) == 1
    assert "multiple claimed Yoke source lanes" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["ruff_changed", "import_check"])
def test_check_refuses_unclaimed_lane(claimed_lanes, command, tmp_path, capsys):
    assert getattr(adapter, command)(["--lane", str(tmp_path)]) == 1
    assert "not a live claimed Yoke source checkout" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["ruff_changed", "import_check"])
@pytest.mark.parametrize(
    "arguments", [["--lane"], ["--lane", "one", "--workdir", "two"]]
)
def test_check_rejects_invalid_selection(command, arguments, capsys):
    with pytest.raises(SystemExit) as error:
        getattr(adapter, command)(arguments)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["ruff_changed", "import_check"])
def test_check_help_teaches_selection(command, capsys):
    assert getattr(adapter, command)(["--help"]) == 0
    help_text = capsys.readouterr().out
    assert "--lane PATH | --workdir PATH" in help_text
