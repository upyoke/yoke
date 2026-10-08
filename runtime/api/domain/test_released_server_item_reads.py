"""Public clients preserve identity across released-server response shapes."""

from types import SimpleNamespace

import pytest

from runtime.api.merge_worktree_tests_ci_helpers import (
    bind_candidate_tree,
    merge_ctx,
    stub_lane,
)
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain.merge_queue_landing_record import record_from_payload
from yoke_core.domain import qa_plan_execution_begin_validation as validation
from yoke_core.engines import merge_worktree_tests_ci as ci


def test_merge_ci_uses_resolved_ref_for_inputs_and_evidence(monkeypatch, tmp_path):
    head = "b" * 40
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: "55",
        await_result=lambda **kwargs: (0, "success"),
    )
    inputs, writes = [], []
    monkeypatch.setattr(
        ci.qa_case_ci_candidate_inputs,
        "item_inputs",
        lambda **kwargs: inputs.append(kwargs) or {},
    )
    monkeypatch.setattr(
        ci,
        "call_dispatcher",
        lambda **kwargs: (
            writes.append(kwargs)
            or SimpleNamespace(success=True, result={"qa_run_id": 901})
        ),
    )
    monkeypatch.setattr(
        ci.merge_ci_verification_wait, "record_wait_and_warn", lambda **kwargs: None
    )
    ctx = merge_ctx(tmp_path, item_id="3989")
    ctx.public_ref = "PLAT-193"
    assert (
        ci.run_ci_verification(ctx, scope="full", command="python3 verify.py") is None
    )
    assert inputs[0]["item_id"] == ctx.public_ref
    assert writes[0]["target"].public_ref == ctx.public_ref
    assert writes[0]["target"].item_id is None


@pytest.mark.parametrize(
    "holder_id,holder_ref,holder_session,expected",
    [
        (3989, None, "session-1", ""),
        (3990, None, "session-1", "different item"),
        (3989, "PLAT-194", "session-1", "different item"),
        (3989, None, "session-2", "another session"),
        (None, None, "session-1", "different item"),
    ],
)
def test_released_holder_is_checked_against_resolved_item(
    monkeypatch, holder_id, holder_ref, holder_session, expected
):
    holder = {"scope": {"item_id": holder_id}, "session_id": holder_session}
    if holder_ref:
        holder["scope"]["public_ref"] = holder_ref
    lookup = {
        "caller_session_id": "session-1",
        "requested_public_ref": "PLAT-193",
        "connection": "prod",
        "function_id": "claims.work.holder_get",
        "response": SimpleNamespace(success=True, result={"holder": holder}),
    }
    detail_reads = []
    monkeypatch.setattr(
        merge_cli,
        "call_dispatcher",
        lambda **kwargs: (
            detail_reads.append(kwargs)
            or SimpleNamespace(
                success=True, result={"item": {"id": 3989, "public_ref": "PLAT-193"}}
            )
        ),
    )
    monkeypatch.setattr(
        recovery,
        "call_dispatcher",
        lambda **kwargs: pytest.fail("holder admission must reuse the original read"),
    )
    with recovery.bind_work_claim_lookup(lookup):
        item, error = merge_cli._resolve_item("PLAT-193", None)
        assert not error and item["public_ref"] == "PLAT-193"
        actual = recovery.claim_error("PLAT-193", "session-1")
        assert actual == "" if not expected else expected in actual
    assert len(detail_reads) == 1
    assert "resolved_item" not in lookup


def test_legacy_holder_without_verified_resolution_is_refused():
    lookup = {
        "function_id": "claims.work.holder_get",
        "response": SimpleNamespace(
            success=True,
            result={
                "holder": {
                    "scope": {"item_id": 3989},
                    "session_id": "session-1",
                }
            },
        ),
    }
    with recovery.bind_work_claim_lookup(lookup):
        assert "different item" in recovery.claim_error("PLAT-193", "session-1")


def landing_payload():
    return {
        "item_id": 3989,
        "project_id": 1,
        "pr_number": "42",
        "state": "landed",
        "queue_holding": "ENQUEUED",
        "queue_entry_state": "ENTRY_PRESENT",
        "merge_when_ready": "CONSUMED",
        "head_sha": "b" * 40,
    }


def test_released_landing_uses_the_request_ref_without_exposing_the_owned_key():
    record = record_from_payload(landing_payload(), expected_public_ref="PLAT-193")
    assert record.public_ref == "PLAT-193"
    assert not hasattr(record, "item_id")


@pytest.mark.parametrize("public_ref", [None, "3989", "PLAT-194"])
def test_explicit_bad_landing_identity_cannot_use_the_request_fallback(public_ref):
    with pytest.raises(ValueError):
        record_from_payload(
            {**landing_payload(), "public_ref": public_ref},
            expected_public_ref="PLAT-193",
        )


def test_legacy_landing_without_request_identity_is_refused():
    with pytest.raises(ValueError, match="public_item_ref_required"):
        record_from_payload(landing_payload())


def test_released_qa_roster_uses_known_subject_without_mutating_attestation(
    monkeypatch,
):
    target = {"subject": {"item_id": 3989}, "environment": {"name": "production"}}
    requirement = {"item_id": 3989, "requirement_id": 7}
    execution = {
        "item_id": 3989,
        "requirements": [requirement],
        "execution_target": target,
        "execution_target_digest": "issued-digest",
    }
    monkeypatch.setattr(validation, "resolve_plan_machine", lambda *args: None)
    monkeypatch.setattr(
        validation, "resolve_execution_base_url", lambda *args: "https://example.test"
    )
    begun = validation.validate_begun_execution(
        execution, machine=None, base_url="", public_ref="PLAT-193"
    )
    assert begun.requirements[0]["public_ref"] == "PLAT-193"
    assert "public_ref" not in requirement
    assert execution["execution_target"] is target
    assert execution["execution_target_digest"] == "issued-digest"
    requirement["item_id"] = 3990
    with pytest.raises(validation.QaPlanExecutionError, match="different item"):
        validation.validate_begun_execution(
            execution, machine=None, base_url="", public_ref="PLAT-193"
        )


@pytest.mark.parametrize("include_owned_key", [True, False])
def test_merge_preparation_keeps_branch_ref_with_either_detail_shape(
    monkeypatch, tmp_path, include_owned_key
):
    from yoke_core.engines import merge_worktree_prepare as prepare

    public_ref = "ITEM-17"
    item = {"public_ref": public_ref, "project": {"slug": "yoke"}}
    if include_owned_key:
        item["id"] = 3989
    calls = []
    monkeypatch.setattr(
        prepare,
        "call_dispatcher",
        lambda **kwargs: (
            calls.append(kwargs) or SimpleNamespace(success=True, result={"item": item})
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.worktree.resolve_main_root", lambda: str(tmp_path)
    )
    monkeypatch.setattr(prepare, "_find_worktree", lambda *args: str(tmp_path))
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda slug: tmp_path,
    )
    ctx = prepare.resolve_context(
        prepare.MergeArgs(branch=public_ref, item_id=3989, standalone=True)
    )
    assert ctx.item_id == public_ref and ctx.public_ref == public_ref
    # Item reads address the item by public ref; the project's default-branch
    # read is project-scoped and carries no item identity at all.
    item_calls = [c for c in calls if c["function_id"].startswith("items.")]
    assert item_calls
    assert all(call["target"].public_ref == public_ref for call in item_calls)
    assert all(call["target"].item_id is None for call in calls)
