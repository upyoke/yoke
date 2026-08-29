"""Transport coverage for item-bound deploy-run start over every mode.

Two independent claims are exercised:

* The agent-facing ``yoke deployment-runs start-for-item`` entry routes the
  ``deployment_runs.start_for_item`` function through the connected dispatcher
  (relayed over https, dispatched in-process on a local Postgres connection)
  rather than running the ``start_for_item`` engine in-process on the client.
  The same request envelope therefore reaches the server over https, where the
  engine runs against the server's Postgres.
* When the engine runs server-side with no machine-local checkout, a
  caller-supplied commit ``release_lineage`` is trusted and the git / checkout
  head resolution is skipped, so the run starts with no local checkout. When a
  checkout IS present (the in-process path) the exact-remote-head validation
  still runs, byte-for-byte with the prior behaviour.
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
from yoke_core.engines import runs_start_for_item as composer
from yoke_core.engines.runs_release_lineage import (
    NO_LOCAL_CHECKOUT,
    _resolve_remote_release_head,
    _validate_commit_release_lineage,
)
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
        composer, "start_for_item",
        side_effect=AssertionError("entry must relay, not run the engine"),
    ):
        rc, out, err = _run_cli(
            "deployment-runs", "start-for-item", TEST_ITEM_REF,
            "--release-lineage", _MERGE_SHA,
        )
    assert rc == 0, err
    assert len(_CAPTURED) == 1
    request = _CAPTURED[-1]
    assert request.function == "deployment_runs.start_for_item"
    assert request.target.kind == "item"
    assert request.target.public_ref == TEST_ITEM_REF
    assert request.payload == {"release_lineage": _MERGE_SHA}
    # The composed handler prints the run id resolved server-side.
    assert out.strip() == "run-20260730-001"


def test_start_for_item_entry_opens_no_local_connection():
    # The client entry over https must not touch a local Postgres connection;
    # the whole envelope goes to the server. With dispatch stubbed the entry
    # should never reach a bare connect.
    with mock.patch(
        "yoke_core.domain.db_helpers.connect",
        side_effect=AssertionError("entry path must not open a local connection"),
    ):
        rc, _out, err = _run_cli(
            "deployment-runs", "start-for-item", TEST_ITEM_REF,
            "--release-lineage", _MERGE_SHA,
        )
    assert rc == 0, err
    assert _CAPTURED[-1].function == "deployment_runs.start_for_item"


# --------------------------------------------------------------------------
# Release-lineage git/checkout skip when running with no machine-local checkout
# --------------------------------------------------------------------------


def test_resolve_head_reports_no_local_checkout(monkeypatch):
    monkeypatch.setattr(_CHECKOUT_RESOLVER, lambda *_a, **_k: None)
    sha, error = _resolve_remote_release_head("yoke", "persistent", "stage")
    assert sha == ""
    assert error == NO_LOCAL_CHECKOUT


def test_validate_skips_supplied_lineage_without_local_checkout(monkeypatch):
    monkeypatch.setattr(_CHECKOUT_RESOLVER, lambda *_a, **_k: None)
    # No checkout means no git head to compare against; the git resolvers must
    # never run on this path.
    import yoke_core.domain.deploy_pipeline_gates as gates

    monkeypatch.setattr(
        gates, "resolve_flow_gate_branch",
        lambda *_a, **_k: pytest.fail("git gate-branch resolver must not run"),
    )
    assert _validate_commit_release_lineage(
        "yoke", "persistent", "stage", _MERGE_SHA,
    ) == ""


def test_start_for_item_trusts_supplied_lineage_with_no_checkout(monkeypatch):
    monkeypatch.setattr(
        composer, "_lookup_item_project_and_flow",
        lambda *_a: ("yoke", "yoke-hosted-stage-no-ci-gate"),
    )
    monkeypatch.setattr(
        composer, "cmd_resolve_target",
        lambda *_a, **_k: ("persistent", "stage", "stage"),
    )
    seen = {}

    def _create(project, flow, *, environment, release_lineage, created_by):
        seen["release_lineage"] = release_lineage
        return "run-20260730-002"

    monkeypatch.setattr(composer, "cmd_create_run", _create)
    monkeypatch.setattr(composer, "cmd_add_item", lambda *_a, **_k: "OK")
    monkeypatch.setattr(
        composer, "cmd_validate_composition", lambda *_a, **_k: (True, "ok"),
    )
    monkeypatch.setattr(_CHECKOUT_RESOLVER, lambda *_a, **_k: None)
    import yoke_core.domain.deploy_pipeline_gates as gates

    monkeypatch.setattr(
        gates, "resolve_flow_gate_branch",
        lambda *_a, **_k: pytest.fail("git resolver must not run over https"),
    )

    result = start_for_item(TEST_ITEM_ID, release_lineage=_MERGE_SHA)

    assert result.ok is True
    assert result.run_id == "run-20260730-002"
    # The client-resolved lineage is trusted and passed straight to create-run.
    assert seen["release_lineage"] == _MERGE_SHA


# --------------------------------------------------------------------------
# In-process behaviour preserved: with a checkout present, validation still runs
# --------------------------------------------------------------------------


def test_validate_still_checks_remote_head_with_local_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(_CHECKOUT_RESOLVER, lambda *_a, **_k: tmp_path)
    import yoke_core.domain.deploy_pipeline_gates as gates
    import yoke_core.domain.deploy_pipeline_github_workflow as ghw

    monkeypatch.setattr(
        gates, "resolve_flow_gate_branch", lambda *_a, **_k: "release/stage",
    )
    monkeypatch.setattr(
        ghw, "_resolve_publish_sha", lambda *_a, **_k: (_MERGE_SHA, ""),
    )
    # A lineage equal to the resolved remote head validates clean...
    assert _validate_commit_release_lineage(
        "yoke", "persistent", "stage", _MERGE_SHA,
    ) == ""
    # ...and a divergent lineage is rejected, exactly as the in-process path did.
    divergent = "b" * 40
    message = _validate_commit_release_lineage(
        "yoke", "persistent", "stage", divergent,
    )
    assert "does not equal the exact remote gate-branch commit" in message
