"""Fleet rehearsal of the projects a dispatch ships through input bindings."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import deploy_pipeline_bound_inputs as bound_inputs
from yoke_core.domain import deploy_pipeline_fleet_rehearsal as rehearsal
from yoke_core.domain import migration_preflight_receipt as receipt
from yoke_core.domain.migration_model_fleet_read import DeclaredFleets
from runtime.api.domain.fleet_rehearsal_dispatch_test_helpers import (
    _DIGEST,
    _ENGINE,
    _HISTORY,
    _RELEASE_SHA,
    RELEASE_CHECKOUT,
    _covered,
    _dispatch_through,
    _stable_commit,
    _stage,
)
from runtime.api.domain import fleet_rehearsal_dispatch_test_helpers as helpers

_BOUND_SHA = "c" * 40
_BOUND_HISTORY = ("0001_registry", "0006_route_machine_codes_to_engine")
_REGISTRY = {
    "runner": {"config": {"modules_dir": "services/svc/migrations"}},
    "fleet": {
        "kind": "named_databases",
        "names": ["registry_db"],
        "converge_argv": ["converge"],
        "schema_shape_sources": ["schema.py"],
    },
}
_BINDINGS = {"consumer_sha": {"project": "consumer", "branch": "main"}}


def _declare(monkeypatch, by_project: dict) -> None:
    def read(project: str):
        models = by_project.get(project, {})
        return (
            DeclaredFleets(
                models={
                    name: {k: v for k, v in model.items() if k != "fleet"}
                    for name, model in models.items()
                },
                fleets={name: model["fleet"] for name, model in models.items()},
            ),
            "",
        )

    monkeypatch.setattr(rehearsal, "read_declared", read)


@pytest.fixture
def shipped(monkeypatch):
    """The own project and one bound project, each with one model."""
    _stable_commit(monkeypatch)
    _declare(
        monkeypatch, {"yoke": {"primary": _ENGINE}, "consumer": {"registry": _REGISTRY}}
    )
    histories = {_RELEASE_SHA: _HISTORY, _BOUND_SHA: _BOUND_HISTORY}
    monkeypatch.setattr(
        rehearsal,
        "_release_history",
        lambda _repository, sha, _modules_dir: (histories[sha], ""),
    )
    monkeypatch.setattr(rehearsal.sources, "_bound_checkout", lambda _p: "/consumer")
    monkeypatch.setattr(rehearsal.release_source, "ensure_commit", lambda _r, _s: "")
    store = {
        ("yoke", "prod"): _covered(),
        ("consumer", "prod"): {},
        ("consumer", "stage"): {},
    }
    histories_by_project = {"yoke": _HISTORY, "consumer": _BOUND_HISTORY}

    def coverage(project, model, environment, _history, _digest):
        return dict(store[(project, environment)]), ""

    def run_preflight(args: list[str]) -> int:
        project, model, environment = (
            args[args.index("--project") + 1],
            args[args.index("--model") + 1],
            args[args.index("--model") + 2],
        )
        store[(project, environment)] = _covered(
            entries=histories_by_project[project], model=model
        )
        return 0

    preflight = mock.Mock(side_effect=run_preflight)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_coverage", coverage)
    monkeypatch.setattr(rehearsal, "_run_preflight", preflight)
    _dispatch_through(monkeypatch, workflow)
    return store, preflight, workflow


def _bound_stage() -> dict:
    stage = _stage()
    stage["config"]["input_bindings"] = dict(_BINDINGS)
    return stage


def _dispatch(stage: dict, *, environment: str = "prod", bound=None):
    return helpers.deploy_pipeline_step_runners._dispatch_step_runner(
        stage,
        run_id="run-1",
        member_items=["1"],
        github_repo="upyoke/yoke",
        project="yoke",
        project_repo_path="/repo",
        branch="main",
        first_item="1",
        timeout_min=1,
        fresh=False,
        environment_name=environment,
        bound_inputs={"consumer_sha": _BOUND_SHA} if bound is None else bound,
        gate_branch="main",
        release_lineage=_RELEASE_SHA,
        sd=None,
    )


def test_carried_history_entry_of_a_bound_project_rehearses_its_commit(
    shipped,
) -> None:
    store, preflight, workflow = shipped

    assert _dispatch(_bound_stage()) == (0, "")

    preflight.assert_called_once_with(
        [
            "--checkout",
            str(RELEASE_CHECKOUT),
            "--project",
            "consumer",
            "--model",
            "registry",
            "prod",
            "--record-receipt",
            "--product-sha",
            _BOUND_SHA,
            "--receipt-env",
            "prod",
        ]
    )
    assert (
        receipt.entry_coverage_path("registry", "0006_route_machine_codes_to_engine")
        in store[("consumer", "prod")]
    )
    workflow.assert_called_once()


def test_bound_schema_shape_change_rehearses_though_every_entry_is_covered(
    shipped,
) -> None:
    store, preflight, workflow = shipped
    store[("consumer", "prod")] = _covered(
        entries=_BOUND_HISTORY, shape=False, model="registry"
    )

    assert _dispatch(_bound_stage()) == (0, "")
    preflight.assert_called_once()
    assert store[("consumer", "prod")][
        receipt.schema_shape_coverage_path("registry", _DIGEST)
    ]


def test_covered_bound_and_own_projects_dispatch_without_rehearsal(shipped) -> None:
    store, preflight, workflow = shipped
    store[("consumer", "prod")] = _covered(entries=_BOUND_HISTORY, model="registry")

    assert _dispatch(_bound_stage()) == (0, "")
    preflight.assert_not_called()
    workflow.assert_called_once()


def test_prod_coverage_never_satisfies_stage(shipped) -> None:
    store, preflight, _workflow = shipped
    store[("yoke", "stage")] = _covered()

    assert _dispatch(_bound_stage(), environment="prod") == (0, "")
    assert _dispatch(_bound_stage(), environment="stage") == (0, "")
    assert [call.args[0][6] for call in preflight.call_args_list] == ["prod", "stage"]


@pytest.mark.parametrize(
    ("bound", "expected"),
    [
        ({}, "has no recorded source commit"),
        ({"consumer_sha": ""}, "has no recorded source commit"),
    ],
)
def test_unresolved_bound_commit_refuses_before_dispatch(
    shipped, bound, expected
) -> None:
    _store, preflight, workflow = shipped

    rc, diagnostic = _dispatch(_bound_stage(), bound=bound)

    assert rc == 1 and expected in diagnostic and "re-drive" in diagnostic
    preflight.assert_not_called()
    workflow.assert_not_called()


def test_two_commits_of_one_project_refuse_as_the_wrong_source(shipped) -> None:
    _store, preflight, workflow = shipped
    stage = _bound_stage()
    stage["config"]["input_bindings"]["other_sha"] = _BINDINGS["consumer_sha"]

    rc, diagnostic = _dispatch(
        stage, bound={"consumer_sha": _BOUND_SHA, "other_sha": "d" * 40}
    )

    assert rc == 1 and "two commits of project 'consumer'" in diagnostic
    preflight.assert_not_called()
    workflow.assert_not_called()


def test_bound_project_without_a_checkout_refuses_with_registration(
    shipped, monkeypatch
) -> None:
    _store, preflight, workflow = shipped
    monkeypatch.setattr(rehearsal.sources, "_bound_checkout", lambda _p: None)

    rc, diagnostic = _dispatch(_bound_stage())

    assert rc == 1 and "yoke project register" in diagnostic
    preflight.assert_not_called()
    workflow.assert_not_called()


def test_engine_built_from_other_source_never_records_bound_coverage(
    shipped, monkeypatch
) -> None:
    _store, preflight, workflow = shipped
    _declare(
        monkeypatch, {"yoke": {"primary": _ENGINE}, "consumer": {"tenants": _ENGINE}}
    )
    monkeypatch.setattr(
        rehearsal.release_source,
        "engine_source_mismatch",
        lambda *_a: "the dispatching engine's migration history differs",
    )
    monkeypatch.setattr(
        rehearsal,
        "_coverage",
        lambda project, *_a: ({} if project == "consumer" else _covered(), ""),
    )

    rc, diagnostic = _dispatch(_bound_stage())

    assert rc == 1 and "migration history differs" in diagnostic
    preflight.assert_not_called()
    workflow.assert_not_called()


def test_failed_bound_rehearsal_never_dispatches(shipped, monkeypatch) -> None:
    _store, _preflight, workflow = shipped
    monkeypatch.setattr(rehearsal, "_run_preflight", lambda _args: 5)

    rc, diagnostic = _dispatch(_bound_stage())

    assert rc == 5 and "consumer/prod model registry" in diagnostic
    workflow.assert_not_called()


def test_bound_receipt_not_recorded_never_dispatches(shipped, monkeypatch) -> None:
    _store, _preflight, workflow = shipped
    monkeypatch.setattr(rehearsal, "_run_preflight", lambda _args: 0)

    rc, diagnostic = _dispatch(_bound_stage())

    assert rc == 1 and "receipt does not cover" in diagnostic
    workflow.assert_not_called()


def test_identical_project_commits_rehearse_once(shipped) -> None:
    _store, preflight, workflow = shipped
    stage = _bound_stage()
    stage["config"]["input_bindings"]["also_consumer"] = _BINDINGS["consumer_sha"]
    stage["config"]["input_bindings"]["own"] = {"project": "yoke", "branch": "main"}

    bound = {
        "consumer_sha": _BOUND_SHA,
        "also_consumer": _BOUND_SHA,
        "own": _RELEASE_SHA,
    }
    assert _dispatch(stage, bound=bound) == (0, "")
    assert preflight.call_count == 1
    workflow.assert_called_once()


def test_bound_project_declaring_no_fleet_keeps_its_skip_reason(
    shipped, monkeypatch, capsys
) -> None:
    _store, preflight, workflow = shipped
    none = {"runner": {"config": {}}, "fleet": {"kind": "none", "reason": "one host"}}
    _declare(
        monkeypatch, {"yoke": {"primary": _ENGINE}, "consumer": {"registry": none}}
    )

    assert _dispatch(_bound_stage()) == (0, "")
    assert "consumer model registry declares no live fleet (one host)" in (
        capsys.readouterr().out
    )
    preflight.assert_not_called()


def _prepared(monkeypatch, sha: str) -> None:
    result = {
        "bound_sources": {"inputs": {"consumer_sha": sha}},
        "members": [{"public_ref": "YOK-1"}],
    }
    response = mock.Mock(success=True, result=result, error=None)
    monkeypatch.setattr(bound_inputs, "call_dispatcher", lambda **_kw: response)


@pytest.mark.parametrize(("prepared_sha", "calls"), [(_BOUND_SHA, 0), ("e" * 40, 1)])
def test_preparation_re_bound_commit_is_rehearsed_before_dispatch(
    monkeypatch, prepared_sha, calls
) -> None:
    _prepared(monkeypatch, prepared_sha)
    before_dispatch = mock.Mock(return_value=(4, "uncovered"))

    resolved, diagnostic = bound_inputs.bound_inputs_for_dispatch(
        {"input_bindings": _BINDINGS},
        name="hosted-release",
        run_id="run-1",
        bound_inputs={"consumer_sha": _BOUND_SHA},
        member_items=[],
        before_dispatch=before_dispatch,
    )

    assert before_dispatch.call_count == calls
    assert resolved == {"consumer_sha": prepared_sha}
    assert ("uncovered" in diagnostic) is bool(calls)
