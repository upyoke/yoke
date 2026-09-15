"""Deployment drivers preserve gates against a local admin connection.

Split out of test_deploy_pipeline_https_execution.py so that module stays
under the authored-file line budget; this file owns the "candidate driver
talking to the local *-db-admin connection" half of that coverage, reusing
its shared fixtures and helpers.
"""

from __future__ import annotations

from runtime.api.domain.test_deploy_pipeline_https_execution import (
    FLOW,
    LINEAGE,
    PROJECT,
    _install_test_https,
    _invoke,
    _replace_flow,
    serving_plane,  # noqa: F401 - pytest fixture re-export
)
from yoke_cli.commands.adapters.deployment_execution_authority import (
    execution_connection_error,
)
from yoke_cli.transport import dispatcher as client_dispatcher
from yoke_cli.transport import https as https_transport
from yoke_core.domain import deploy_pipeline, deploy_pipeline_control_plane


def _admin_driver_env(monkeypatch, plane) -> None:
    """The candidate driver's own ambient identity: an admin door, no https."""
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.setenv("YOKE_ACTOR_ID", str(plane["owner_id"]))
    monkeypatch.setattr(
        client_dispatcher, "_resolve_session_id", lambda: plane["owner_session"]
    )
    monkeypatch.setattr(deploy_pipeline, "resolve_project_checkout_path", lambda _p: "")


def _bootstrap_admin_env(monkeypatch, plane) -> None:
    """The admin driver with no https plane reachable at all — not even named."""
    _admin_driver_env(monkeypatch, plane)
    monkeypatch.setattr(
        https_transport, "resolve_https_connection", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        https_transport,
        "relay_https",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local admin bootstrap contacted the serving API")
        ),
    )


_SCOPED_QA_STAGES = [
    {"name": "merged", "step_runner": "auto"},
    {
        "name": "scoped-item-check",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "item",
    },
    {
        "name": "scoped-run-check",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "run",
    },
    {"name": "complete", "step_runner": "auto"},
]


def test_admin_candidate_dispatches_scoped_qa_stages_locally(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
    monkeypatch,
) -> None:
    """An admin-connected candidate evaluates scoped-QA stages in-process.

    No https connection is reachable at all (mirrors
    test_local_admin_candidate_bootstraps_execution_handlers below): any
    attempt to relay raises. Scoped-QA dispatch and resume still succeed,
    proving they went through the same connection-keyed call_dispatcher
    path deploy_pipeline_control_plane uses for every other
    execution-owned operation, landing on the local in-process handler
    rather than failing for want of a serving plane.
    """
    conn = serving_plane["conn"]
    _replace_flow(conn, _SCOPED_QA_STAGES)
    _bootstrap_admin_env(monkeypatch, serving_plane)

    run_id = str(
        _invoke(
            "deployment_runs.create",
            {"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
        )["run_id"]
    )
    assert execution_connection_error(run_id) is None

    from yoke_core.domain.deployment_qa_stage_dispatch import (
        dispatch_deployment_qa_stage,
    )
    from yoke_core.domain.deployment_qa_stage_resume import resume_qa_refusal_message

    # Nothing is materialized yet, so the run's own stored flow — read
    # locally, never relayed — is what produces each verdict below.
    code, message = dispatch_deployment_qa_stage(
        {"name": "scoped-item-check"}, run_id=run_id
    )
    assert code == 1
    assert "item-scoped QA stage has no attached run members" in message

    refusal = resume_qa_refusal_message(run_id=run_id, start_stage="complete")
    assert "scoped-run-check" in refusal
    assert "0 current acceptance records" in refusal


def test_https_driver_gets_a_genuine_unknown_function_refusal_from_an_old_build(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
    monkeypatch,
) -> None:
    """An ordinary HTTPS-connected driver relays normally and is refused.

    dispatch_deployment_qa_stage/resume_qa_refusal_message carry no
    special-case "unknown function" handling of their own — they read
    call_dispatcher's ordinary success/failure response exactly like every
    other execution-owned operation. Hiding the two function ids from the
    server-side registry lookup simulates a serving build that predates
    them (an old, pre-scoped-QA build) and proves the caller reaches the
    dispatcher's own genuine "not registered" refusal, unmodified.
    """
    conn = serving_plane["conn"]
    _replace_flow(conn, _SCOPED_QA_STAGES)
    _install_test_https(monkeypatch, serving_plane)

    from yoke_core.domain import yoke_function_dispatch
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        dispatch_deployment_qa_stage,
    )
    from yoke_core.domain.deployment_qa_stage_resume import (
        RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION,
        resume_qa_refusal_message,
    )

    real_lookup = yoke_function_dispatch.lookup
    missing_on_the_old_build = {
        DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION,
    }

    def lookup_on_an_old_build(function_id: str):
        if function_id in missing_on_the_old_build:
            return None
        return real_lookup(function_id)

    monkeypatch.setattr(yoke_function_dispatch, "lookup", lookup_on_an_old_build)

    run_id = str(
        _invoke(
            "deployment_runs.create",
            {"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
        )["run_id"]
    )

    code, message = dispatch_deployment_qa_stage(
        {"name": "scoped-item-check"}, run_id=run_id
    )
    assert code == 1
    assert "is not registered" in message
    assert DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION in message

    try:
        resume_qa_refusal_message(run_id=run_id, start_stage="complete")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "is not registered" in str(exc)
        assert RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION in str(exc)


def test_local_admin_candidate_bootstraps_execution_handlers(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
    monkeypatch,
) -> None:
    conn = serving_plane["conn"]
    _replace_flow(
        conn,
        [
            {"name": "bootstrap", "step_runner": "auto", "qa_kind": "bootstrap"},
            {"name": "complete", "step_runner": "auto"},
        ],
    )
    _bootstrap_admin_env(monkeypatch, serving_plane)

    called: list[str] = []
    original_call = deploy_pipeline_control_plane._call

    def record_call(function_id: str, run_id: str, payload: dict):
        called.append(function_id)
        return original_call(function_id, run_id, payload)

    monkeypatch.setattr(deploy_pipeline_control_plane, "_call", record_call)
    run_id = str(
        _invoke(
            "deployment_runs.create",
            {"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
        )["run_id"]
    )
    assert execution_connection_error(run_id) is None
    assert deploy_pipeline.run_pipeline(run_id) == deploy_pipeline.EXIT_SUCCESS
    assert {
        "deployment_runs.execution.context",
        "deployment_runs.execution.update",
        "deployment_runs.execution.qa_seed",
        "deployment_runs.execution.qa_record",
        "deployment_runs.execution.qa_pending",
    }.issubset(called)
