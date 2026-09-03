"""Where a pytest run executes: routing, refusals, and the watcher's remote branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.tools import (
    pytest_remote_selection as routing,
    watch_pytest,
    watch_pytest_remote,
)
from yoke_core.tools._watch_throttle import LineClass


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture()
def lane_repo(tmp_path: Path, monkeypatch) -> Path:
    """A committed lane branch off ``main`` with the selection workflow present."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", "git@github.com:acme/widgets.git")
    workflow = root / routing.WORKFLOWS_DIR / routing.DEFAULT_SELECTION_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: selection\n")
    (root / "module.py").write_text("X = 1\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "PRJ-7")
    (root / "module.py").write_text("X = 2\n")
    _git(root, "commit", "-q", "-am", "lane change")
    monkeypatch.delenv(routing.LOCAL_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.project_ci_workflow.project_ci_workflow_settings",
        lambda project: {"workflow_file": "ci.yml"},
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.repo_slug", lambda _root: "acme/widgets",
    )
    # A pytest child runs with the machine config deliberately hidden, so the
    # real lookup answers None here and would route every case below locally.
    monkeypatch.setattr(
        "yoke_core.domain.yoke_connected_env.load_active", lambda *a, **k: object(),
    )
    return root


def _route(root: Path, **overrides):
    kwargs = {"pytest_args": ["-q"], "impacted_base": "main"}
    kwargs.update(overrides)
    return routing.resolve_route(root, **kwargs)


def test_clean_lane_on_a_ci_project_routes_remote(lane_repo: Path) -> None:
    route = _route(lane_repo, pytest_args=["-n", "4", "--rootdir", str(lane_repo), "-q"])

    assert isinstance(route, routing.RemoteRoute)
    assert route.branch == "PRJ-7"
    assert route.head_sha == _git(lane_repo, "rev-parse", "HEAD")
    assert route.base_sha == _git(lane_repo, "merge-base", "main", "HEAD")
    assert route.repo == "acme/widgets"
    assert route.workflow == routing.DEFAULT_SELECTION_WORKFLOW_FILE
    assert route.pytest_args == ("-q",)
    assert route.dropped_args == ("-n", "4", "--rootdir", str(lane_repo))


def test_dispatch_id_is_a_function_of_tree_and_selection(lane_repo: Path) -> None:
    first = _route(lane_repo, pytest_args=["-q"])
    again = _route(lane_repo, pytest_args=["-q"])
    other = _route(lane_repo, pytest_args=["-q", "-k", "x"])

    assert first.dispatch_id == again.dispatch_id
    assert first.dispatch_id != other.dispatch_id
    assert first.head_sha in first.dispatch_id


def test_explicit_paths_without_impacted_have_no_selection_base(lane_repo: Path) -> None:
    route = _route(lane_repo, pytest_args=["tests/test_a.py"], impacted_base=None)

    assert isinstance(route, routing.RemoteRoute)
    assert route.base_sha == ""
    assert "--base-sha" in route.engine_argv()


def test_local_flag_env_and_ci_stay_local(lane_repo: Path, monkeypatch) -> None:
    assert isinstance(_route(lane_repo, local=True), routing.LocalRoute)
    assert isinstance(
        _route(lane_repo, env={routing.LOCAL_ENV: "1"}), routing.LocalRoute,
    )
    assert isinstance(_route(lane_repo, env={"CI": "true"}), routing.LocalRoute)


def test_project_without_the_capability_runs_locally(lane_repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.project_ci_workflow.project_ci_workflow_settings",
        lambda project: {},
    )
    route = _route(lane_repo)

    assert isinstance(route, routing.LocalRoute)
    assert "ci_workflow_file" in route.reason


def test_tree_without_the_selection_workflow_runs_locally(lane_repo: Path) -> None:
    (lane_repo / routing.WORKFLOWS_DIR / routing.DEFAULT_SELECTION_WORKFLOW_FILE).unlink()
    _git(lane_repo, "commit", "-q", "-am", "drop workflow")

    route = _route(lane_repo)

    assert isinstance(route, routing.LocalRoute)
    assert routing.DEFAULT_SELECTION_WORKFLOW_FILE in route.reason


def test_process_without_a_control_plane_binding_runs_locally(
    lane_repo: Path, monkeypatch,
) -> None:
    """A detached process has no declaration to read, so it is not an outage.

    The source-dev runner hides the machine config from its children on
    purpose. Refusing there would turn the sanctioned way to run a lane's
    own tests into a dead end, so the honest answer is the one an
    undeclared project already gets: run here, and say why.
    """
    monkeypatch.setattr(
        "yoke_core.domain.yoke_connected_env.load_active", lambda *a, **k: None,
    )

    route = _route(lane_repo)

    assert isinstance(route, routing.LocalRoute)
    assert "control-plane connection" in route.reason


def test_unreachable_control_plane_refuses_and_names_local(lane_repo: Path, monkeypatch) -> None:
    def boom(project):
        raise RuntimeError("relay down")

    monkeypatch.setattr(
        "yoke_core.domain.project_ci_workflow.project_ci_workflow_settings", boom,
    )
    route = _route(lane_repo)

    assert isinstance(route, routing.Refusal)
    assert route.exit_code == routing.EXIT_UNREACHABLE
    assert "relay down" in route.message
    assert routing.LOCAL_FLAG in route.message


def test_dirty_tree_is_refused_with_commit_then_run(lane_repo: Path) -> None:
    (lane_repo / "module.py").write_text("X = 3\n")
    (lane_repo / "scratch.txt").write_text("untracked\n")

    route = _route(lane_repo)

    assert isinstance(route, routing.Refusal)
    assert route.exit_code == routing.EXIT_REFUSED
    assert "module.py" in route.message and "scratch.txt" in route.message
    assert "Commit, then run" in route.message


def test_checkout_on_the_base_branch_is_refused(lane_repo: Path) -> None:
    _git(lane_repo, "checkout", "-q", "main")

    route = _route(lane_repo)

    assert isinstance(route, routing.Refusal)
    assert route.exit_code == routing.EXIT_REFUSED
    assert "on main" in route.message


def test_strip_machine_local_args_handles_equals_forms() -> None:
    kept, dropped = routing.strip_machine_local_args(
        ["--numprocesses=8", "-k", "expr", "--rootdir=/x", "tests/"]
    )
    assert kept == ("-k", "expr", "tests/")
    assert dropped == ("--numprocesses=8", "--rootdir=/x")


def test_selection_workflow_honours_the_declared_override() -> None:
    assert routing.selection_workflow({}) == routing.DEFAULT_SELECTION_WORKFLOW_FILE
    assert routing.selection_workflow(
        {routing.SELECTION_WORKFLOW_KEY: "tests-on-ci.yml"}
    ) == "tests-on-ci.yml"


# --- the watcher's remote branch --------------------------------------------


def _remote_route(root: Path) -> routing.RemoteRoute:
    return routing.RemoteRoute(
        root=root, project="yoke", workflow="sel.yml", repo="acme/widgets",
        branch="PRJ-7", head_sha="a" * 40, base_sha="b" * 40, pytest_args=("-q",),
    )


def _stub_watch_preflight(monkeypatch) -> None:
    monkeypatch.setattr(
        watch_pytest.verification_tree_binding, "evaluate_run",
        lambda **_: watch_pytest.verification_tree_binding.TreeBindingVerdict(),
    )


def test_watch_pytest_skips_local_selection_and_runs_remote(monkeypatch, tmp_path) -> None:
    _stub_watch_preflight(monkeypatch)
    monkeypatch.setattr(watch_pytest, "_route", lambda ns, args, root: _remote_route(tmp_path))
    monkeypatch.setattr(
        watch_pytest, "_impacted_selection",
        lambda *a, **k: pytest.fail("the selection is CI's job on a remote run"),
    )
    calls: dict = {}

    def fake_remote_run(route, **kwargs):
        calls["route"] = route
        calls.update(kwargs)
        return 1

    monkeypatch.setattr(watch_pytest_remote, "run", fake_remote_run)

    assert watch_pytest.main(["--impacted", "main", "--bounded"]) == 1
    assert calls["route"].head_sha == "a" * 40
    assert calls["kind"] == watch_pytest.KIND


def test_watch_pytest_relays_a_routing_refusal(monkeypatch, capsys) -> None:
    _stub_watch_preflight(monkeypatch)
    monkeypatch.setattr(
        watch_pytest, "_route",
        lambda ns, args, root: routing.Refusal("Error: remote selection: dirty", 2),
    )

    assert watch_pytest.main(["--impacted", "main"]) == 2
    assert "remote selection: dirty" in capsys.readouterr().err


def test_widen_is_a_local_run_by_definition(monkeypatch) -> None:
    seen: dict = {}

    def fake_resolve(root, *, pytest_args, impacted_base, local=False, env=None):
        seen["local"] = local
        return routing.LocalRoute("test")

    monkeypatch.setattr(routing, "resolve_route", fake_resolve)
    monkeypatch.setattr(watch_pytest, "_impacted_selection", lambda *a, **k: None)

    watch_pytest.main(["--impacted", "main", "--widen"])

    assert seen["local"] is True


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Error: remote selection: push refused", LineClass.URGENT),
        (f"{routing.PREFIX} dispatched run=1 url", LineClass.SUMMARY),
        ("  Workflow status: in_progress (elapsed: 30s, next poll: 20s)", LineClass.PROGRESS),
        ("  GitHub Actions status via relay", LineClass.NOISE),
        ("FAILED runtime/api/test_x.py::test_y - assert", LineClass.URGENT),
    ],
)
def test_remote_line_classification(line: str, expected: LineClass) -> None:
    assert watch_pytest_remote.classify_remote_line(line).cls == expected


def test_remote_header_names_the_run_and_the_opt_out(tmp_path) -> None:
    route = routing.RemoteRoute(
        root=tmp_path, project="yoke", workflow="sel.yml", repo="acme/widgets",
        branch="PRJ-7", head_sha="a" * 40, base_sha="", pytest_args=("-q",),
        dropped_args=("-n", "0"),
    )
    header = watch_pytest_remote.header(route, "pytest")

    assert "sel.yml on acme/widgets@PRJ-7" in header
    assert "base=explicit paths" in header
    assert "dropped machine-local args -n 0" in header
    assert routing.LOCAL_FLAG in header
