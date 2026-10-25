"""Transport coverage for item-bound deploy-run start over every mode.

Two independent claims are exercised:

* The agent-facing ``yoke deployment-runs start-for-item`` entry routes the
  ``deployment_runs.start_for_item`` function through the connected dispatcher
  (relayed over https, dispatched in-process on a local Postgres connection)
  rather than running the ``start_for_item`` engine in-process on the client.
  The same request envelope therefore reaches the server over https, where the
  engine runs against the server's Postgres.
* The engine binds its release source from GitHub, as ``deployment-runs
  create`` does, so a server with no machine-local checkout binds the gate
  branch tip without reading any checkout or git ref.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest import mock

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain import deployment_run_gate_branch_lineage as lineage
from yoke_core.domain.deployment_run_create_write import CreatedRun
from yoke_core.engines import runs_start_for_item as composer
from yoke_core.engines.runs_start_for_item import start_for_item

# Synthetic fixture id kept off the literal so the doc-hygiene drift guard
# stays clean; every reference is built from the constant.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"

_MERGE_SHA = "a" * 40
_CHECKOUT_RESOLVER = (
    "yoke_core.domain.project_checkout_locations.checkout_for_project_slug"
)


# --------------------------------------------------------------------------
# Entry relay: the CLI routes through the dispatcher, not the in-process engine
# --------------------------------------------------------------------------

_CAPTURED: List[FunctionCallRequest] = []


@pytest.fixture(autouse=True)
def _reset_captured():
    _CAPTURED.clear()


def _stub_dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={
            "run_id": "run-20260730-001",
            "item_id": TEST_ITEM_ID,
            "project": "yoke",
            "flow": "yoke-hosted-stage-no-ci-gate",
            "target_tier": "persistent",
            "target_environment_id": "stage",
            "target_environment_name": "stage",
        },
    )


def _run_cli(*argv: str) -> tuple[int, str, str]:
    with mock.patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with mock.patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_dispatch,
        ):
            with mock.patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = cli_main(list(argv))
                return rc, out.getvalue(), err.getvalue()


def test_start_for_item_entry_relays_through_dispatcher():
    # If the entry ran the engine in-process it would call this; the relay must
    # not, so a call here is a hard failure.
    with mock.patch.object(
        composer,
        "start_for_item",
        side_effect=AssertionError("entry must relay, not run the engine"),
    ):
        rc, out, err = _run_cli(
            "deployment-runs",
            "start-for-item",
            TEST_ITEM_REF,
            "--release-lineage",
            _MERGE_SHA,
        )
    assert rc == 0, err
    assert len(_CAPTURED) == 1
    request = _CAPTURED[-1]
    assert request.function == "deployment_runs.start_for_item"
    assert request.target.kind == "item"
    assert request.target.public_ref == TEST_ITEM_REF
    assert request.payload == {"release_lineage": _MERGE_SHA}
    # The composed handler prints the run id resolved server-side.
    assert "run id: run-20260730-001" in out


def test_start_for_item_entry_opens_no_local_connection():
    # The client entry over https must not touch a local Postgres connection;
    # the whole envelope goes to the server. With dispatch stubbed the entry
    # should never reach a bare connect.
    with mock.patch(
        "yoke_core.domain.db_helpers.connect",
        side_effect=AssertionError("entry path must not open a local connection"),
    ):
        rc, _out, err = _run_cli(
            "deployment-runs",
            "start-for-item",
            TEST_ITEM_REF,
            "--release-lineage",
            _MERGE_SHA,
        )
    assert rc == 0, err
    assert _CAPTURED[-1].function == "deployment_runs.start_for_item"


# --------------------------------------------------------------------------
# Source binding reads GitHub, never a machine-local checkout
# --------------------------------------------------------------------------


def test_start_for_item_binds_the_tip_from_github_with_no_checkout(monkeypatch):
    monkeypatch.setattr(
        composer,
        "_lookup_item_project_and_flow",
        lambda *_a: ("platform", "platform-prod-commit-delivery-hosted"),
    )
    monkeypatch.setattr(
        composer, "cmd_resolve_target", lambda *_a, **_k: ("persistent", 7, "prod")
    )
    monkeypatch.setattr(composer, "delivery_owner", lambda *_a: None)
    monkeypatch.setattr(
        tested,
        "ci_gate_target",
        lambda *_a: tested.CiGateTarget(
            "platform", "flow", "o/platform", "ci.yml", "main", "t", "prod"
        ),
    )
    monkeypatch.setattr(lineage, "previous_release", lambda *_a: None)
    runs = [{"id": 9, "run_number": 9, "head_sha": _MERGE_SHA, "head_branch": "PLAT-1",
             "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}]

    def _read(_target, path, query):
        if path.endswith("/commits"):
            return [{"sha": _MERGE_SHA}]
        return {"workflow_runs": runs if query.get("head_sha") == _MERGE_SHA else []}

    monkeypatch.setattr(tested, "_read", _read)
    monkeypatch.setattr(
        tested, "dispatch_branch_ci", lambda *_a: pytest.fail("proof exists; no dispatch")
    )
    monkeypatch.setattr(
        _CHECKOUT_RESOLVER,
        lambda *_a, **_k: pytest.fail("binding must not read a checkout"),
    )
    seen = {}

    def _create(project, flow, item_id, **kwargs):
        seen["release_lineage"] = kwargs["release_lineage"]
        return (CreatedRun("run-20260730-002", False, None), "ok")

    monkeypatch.setattr(composer, "create_item_run", _create)

    result = start_for_item(TEST_ITEM_ID)

    assert result.ok is True
    assert seen["release_lineage"] == _MERGE_SHA
    assert result.to_dict()["release_lineage"] == _MERGE_SHA
