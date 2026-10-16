"""Exercise full-suite admission at the shared router and both command callers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import verification_tree_binding as binding
from yoke_core.tools import pytest_remote_full_scope as admission
from yoke_core.tools import pytest_remote_selection as routing
from yoke_core.tools import run_tests, watch_pytest

pytestmark = pytest.mark.usefixtures("bound_project_context")
ROOTS = ("specs/unit/", "specs/integration/")
GATE = {"registered_scope": "full", "ci_workflow": "checks.yml"}


@pytest.fixture()
def remote_lane(tmp_path, monkeypatch):
    for anchor in ROOTS:
        (tmp_path / anchor).mkdir(parents=True)
    workflow = (
        tmp_path / routing.WORKFLOWS_DIR / routing.DEFAULT_SELECTION_WORKFLOW_FILE
    )
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: selection\n")
    monkeypatch.setattr(routing, "required_local_project", lambda *a, **k: "widgets")
    monkeypatch.setattr(
        "yoke_core.domain.yoke_connected_env.load_active", lambda: object()
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_ci_workflow.project_ci_workflow_settings",
        lambda _: {"workflow_file": "checks.yml"},
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.repo_slug", lambda _: "acme/widgets"
    )
    monkeypatch.setattr(routing, "dirty_paths", lambda _: [])
    monkeypatch.setattr(
        routing,
        "_git",
        lambda root, *args: "feature" if "--abbrev-ref" in args else "a" * 40,
    )
    monkeypatch.setattr(admission, "resolve_test_roots", lambda _: ROOTS)
    monkeypatch.setattr(binding, "ambient_session_id", lambda: "fixture-session")
    monkeypatch.setattr(
        binding,
        "resolve_claim_worktrees",
        lambda _: binding.ClaimLookup(worktrees=(str(tmp_path),), lane_item_id="PRJ-7"),
    )
    monkeypatch.setattr(
        binding, "evaluate_run", lambda **_: binding.TreeBindingVerdict()
    )
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == "qa.plan.get":
            result = {
                "plan": {"cases": [{"method_id": "command-ci", "method_config": GATE}]}
            }
        else:
            result = {
                "rows": [{"id": 71, "method_id": "command-ci", "method_config": GATE}]
            }
        return SimpleNamespace(success=True, result=result)

    monkeypatch.setattr(admission, "call_dispatcher", dispatch)
    monkeypatch.delenv(routing.LOCAL_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    return tmp_path, calls


def route(root, args, **kwargs):
    return routing.resolve_route(
        root, pytest_args=args, impacted_base=None, env={}, **kwargs
    )


@pytest.mark.parametrize(
    "targets", [ROOTS, (".",), ("./specs/",), ("specs/unit", "specs/integration/")]
)
def test_complete_coverage_refuses_before_git_publication(
    remote_lane, monkeypatch, targets
):
    root, calls = remote_lane
    monkeypatch.setattr(
        routing, "_git", lambda *a, **k: pytest.fail("git boundary reached")
    )
    result = route(root, targets)
    assert isinstance(result, routing.Refusal)
    assert result.exit_code == routing.EXIT_REFUSED
    assert "redundant_full_suite" in result.message
    assert "yoke qa case run --requirement-id 71" in result.message
    assert "Nothing was pushed or dispatched" in result.message
    assert calls[0]["payload"]["plan_id"] == "registered-command-full"
    assert calls[1]["target"].public_ref == "PRJ-7"


@pytest.mark.parametrize(
    "args",
    [
        ["specs/unit/test_a.py"],
        ["specs/unit/test_a.py::test_one"],
        ["specs/unit/"],
        [*ROOTS, "-k", "routing"],
        [*ROOTS, "-krouting"],
        [*ROOTS, "-k=routing"],
        [*ROOTS, "-m", "slow"],
        [*ROOTS, "-mslow"],
        [*ROOTS, "--collect-only"],
        [*ROOTS, "--co"],
        [*ROOTS, "--ignore-glob=*_slow.py"],
        [*ROOTS, "--deselect", "specs/unit/test_a.py::test_one"],
        [*ROOTS, "--lf"],
        [*ROOTS, "--stepwise"],
        [*ROOTS, "--splits=2", "--group=1"],
        ["-q"],
    ],
)
def test_targeted_filtered_and_collection_routes_still_remote(remote_lane, args):
    root, calls = remote_lane
    assert isinstance(route(root, args), routing.RemoteRoute)
    assert not calls


@pytest.mark.parametrize(
    "args", [[*ROOTS, "-k", ""], [*ROOTS, "-m="], [*ROOTS, "-k", "routing", "-k", ""]]
)
def test_empty_effective_filter_is_diagnosed(remote_lane, args):
    root, _ = remote_lane
    result = route(root, args)
    assert isinstance(result, routing.Refusal)
    assert "Empty -k/-m expressions do not filter tests" in result.message


@pytest.mark.parametrize("env", [{"CI": "true"}, {routing.LOCAL_ENV: "1"}])
def test_already_ci_and_local_outage_fallback_bypass(remote_lane, env):
    root, calls = remote_lane
    result = routing.resolve_route(root, pytest_args=ROOTS, impacted_base=None, env=env)
    assert isinstance(result, routing.LocalRoute)
    assert not calls
    assert isinstance(route(root, ROOTS, local=True), routing.LocalRoute)


@pytest.mark.parametrize(
    "plan",
    [
        {},
        {"retired_at": "retired"},
        {"cases": [{"method_id": "command", "method_config": GATE}]},
        {
            "cases": [
                {
                    "method_id": "command-ci",
                    "method_config": {"registered_scope": "full"},
                }
            ]
        },
    ],
)
def test_no_available_registered_full_ci_gate_preserves_selection(
    remote_lane, monkeypatch, plan
):
    root, _ = remote_lane
    monkeypatch.setattr(
        admission,
        "call_dispatcher",
        lambda **_: SimpleNamespace(success=True, result={"plan": plan}),
    )
    assert isinstance(route(root, ROOTS), routing.RemoteRoute)


def test_unknown_roots_do_not_guess_coverage(remote_lane, monkeypatch):
    root, calls = remote_lane
    monkeypatch.setattr(admission, "resolve_test_roots", lambda _: ())
    assert isinstance(route(root, ROOTS), routing.RemoteRoute)
    assert not calls


def test_recovery_lookup_failure_still_refuses_proven_full_scope(
    remote_lane, monkeypatch
):
    root, _ = remote_lane
    monkeypatch.setattr(
        admission,
        "_recovery",
        lambda *a: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    result = route(root, ROOTS)
    assert isinstance(result, routing.Refusal)
    assert "yoke qa requirement list --project widgets" in result.message


def test_requirement_absent_teaches_item_lookup(remote_lane, monkeypatch):
    root, _ = remote_lane
    monkeypatch.setattr(
        admission,
        "call_dispatcher",
        lambda **_: SimpleNamespace(success=True, result={"rows": []}),
    )
    assert (
        admission._recovery(root, "widgets", GATE)
        == "yoke qa requirement list --item PRJ-7"
    )


def test_both_public_callers_refuse_without_remote_engine(
    remote_lane, monkeypatch, capsys
):
    root, _ = remote_lane
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        watch_pytest.watch_pytest_remote,
        "run",
        lambda *a, **k: pytest.fail("dispatched"),
    )
    monkeypatch.setattr(
        run_tests, "_run_remote", lambda *a, **k: pytest.fail("dispatched")
    )
    assert watch_pytest.main(["--", *ROOTS]) == routing.EXIT_REFUSED
    assert run_tests.run(ROOTS, repo_root=root) == routing.EXIT_REFUSED
    output = capsys.readouterr()
    assert "redundant_full_suite" in output.out + output.err


def test_full_roots_used_only_as_option_values_are_not_coverage(remote_lane):
    root, calls = remote_lane
    assert isinstance(
        route(root, ["--rootdir", ROOTS[0], "--basetemp", ROOTS[1]]),
        routing.RemoteRoute,
    )
    assert not calls


def test_unreadable_gate_does_not_assert_availability(remote_lane, monkeypatch):
    root, _ = remote_lane
    monkeypatch.setattr(
        admission, "call_dispatcher", lambda **_: SimpleNamespace(success=False)
    )
    assert isinstance(route(root, ROOTS), routing.RemoteRoute)


def test_marker_expression_as_plugin_operand_is_not_a_filter(remote_lane):
    root, _ = remote_lane
    result = route(root, [*ROOTS, "-p", "-mslow"])
    assert isinstance(result, routing.Refusal)


def test_impacted_iteration_retains_the_change_selection(remote_lane):
    root, calls = remote_lane
    result = routing.resolve_route(
        root, pytest_args=["-q"], impacted_base="main", env={}
    )
    assert isinstance(result, routing.RemoteRoute)
    assert result.base_sha
    assert not calls


@pytest.mark.parametrize(
    "obsolete",
    [
        {"waived_at": "waived"},
        {"replacement_requirement_id": 72},
        {"superseded_by_requirement_id": 72},
        {"deployment_run_id": "fixture-run"},
        {"qa_phase": "post_deploy"},
    ],
)
def test_recovery_skips_unusable_attached_cases(remote_lane, monkeypatch, obsolete):
    root, _ = remote_lane
    rows = [
        {"id": 70, "method_id": "command-ci", "method_config": GATE, **obsolete},
        {"id": 71, "method_id": "command-ci", "method_config": GATE},
    ]
    monkeypatch.setattr(
        admission,
        "call_dispatcher",
        lambda **_: SimpleNamespace(success=True, result={"rows": rows}),
    )
    assert (
        admission._recovery(root, "widgets", GATE)
        == "yoke qa case run --requirement-id 71"
    )
