"""Admission shapes consume registered handler envelopes, not guessed keys."""

from types import SimpleNamespace

from runtime.api.conftest import insert_item
from runtime.api.merge_queue_landing_test_helpers import dispatch_for, ok_response
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.handlers import reads, shepherd_reads
from yoke_core.domain.handlers.reads import ItemsGetResponse
from yoke_core.domain.handlers.shepherd_reads import ShepherdDependencyListResponse
from yoke_core.domain.merge_queue_admission import (
    REFUSE_MIGRATION_CARRIER,
    REFUSE_SERIAL_ORDERING,
    TrainCandidate,
    evaluate_admission,
)
from yoke_core.domain.merge_queue_admission_shape import (
    candidate_shape,
    train_context,
)
from yoke_core.domain.shepherd_dependency import cmd_dependency_add
from yoke_core.domain.shepherd_dependency_read import DEPENDENCY_LIST_COLUMNS


def _items_get_request(item_id, fields):
    return FunctionCallRequest(
        function="items.get.run",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={"fields": list(fields)},
    )


def _dep_list_request(item_id):
    return FunctionCallRequest(
        function="shepherd.dependency_list.run",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={},
    )


def test_core_packet_teaches_real_envelopes_and_wrong_guesses():
    from yoke_core.domain import schema_api_context as sac

    body = sac.render_topic_packet("core")
    assert "result.fields.db_mutation_profile" in body
    assert "top-level ``db_mutation_profile``" in body
    assert "projects `direction`/`other_item`" in body
    assert "wrong guess: result keys `dependent_item`/`blocking_item`" in body
    fake = dispatch_for({"YOK-200": {"profile": '{"state":"declared"}'}})
    result = fake(
        function_id="items.get.run",
        target=SimpleNamespace(public_ref="YOK-200"),
    ).result
    ItemsGetResponse.model_validate(result)
    assert "db_mutation_profile" not in result
    assert result["fields"]["db_mutation_profile"] == '{"state":"declared"}'


def test_landing_fake_dependency_list_matches_handler_row_keys():
    row = {name: "" for name in DEPENDENCY_LIST_COLUMNS}
    row["direction"] = "depends-on"
    row["other_item"] = "YOK-150"
    row["gate_point"] = "activation"
    fake = dispatch_for({"YOK-200": {"dependencies": [row]}})
    result = fake(
        function_id="shepherd.dependency_list.run",
        target=SimpleNamespace(public_ref="YOK-200"),
    ).result
    ShepherdDependencyListResponse.model_validate(result)
    emitted = result["dependencies"][0]
    assert "dependent_item" not in emitted
    assert "blocking_item" not in emitted
    assert set(DEPENDENCY_LIST_COLUMNS) <= set(emitted)


def test_blocks_edge_refuses_dependent_against_real_list_projection(test_db):
    insert_item(test_db, id=200, title="dependent")
    insert_item(test_db, id=150, title="blocker")
    cmd_dependency_add(test_db, "YOK-200", "YOK-150", "operator")
    test_db.commit()
    outcome = shepherd_reads.handle_shepherd_dependency_list(
        _dep_list_request(200),
    )
    assert outcome.primary_success
    rows = outcome.result_payload["dependencies"]
    assert rows
    assert all("other_item" in row and "direction" in row for row in rows)
    assert all("dependent_item" not in row for row in rows)

    lane_dispatch = dispatch_for({"YOK-150": {}})

    def dispatch(*, function_id, target, payload=None, **_kw):
        if function_id == DB_READ_FUNCTION_ID:
            return lane_dispatch(
                function_id=function_id,
                target=target,
                payload=payload,
            )
        if function_id == "claims.path.list":
            return ok_response({"claims": []})
        if function_id == "items.get.run":
            return ok_response({"item_id": 0, "fields": {"db_mutation_profile": ""}})
        if function_id == "shepherd.dependency_list.run":
            return ok_response(outcome.result_payload)
        raise AssertionError(function_id)

    context, err = train_context(dispatch, "YOK-200", ("YOK-150",))
    assert err is None
    verdict = evaluate_admission(TrainCandidate(public_ref="YOK-200"), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_SERIAL_ORDERING


def test_migration_carrier_reads_fields_nested_items_get(test_db):
    profile = '{"state":"declared"}'
    insert_item(test_db, id=200, db_mutation_profile=profile)
    insert_item(test_db, id=150, db_mutation_profile=profile)
    payloads = {}

    lane_dispatch = dispatch_for({"YOK-150": {}})

    def dispatch(*, function_id, target, payload=None, **_kw):
        if function_id == DB_READ_FUNCTION_ID:
            return lane_dispatch(
                function_id=function_id,
                target=target,
                payload=payload,
            )
        item_id = int(str(target.public_ref).rsplit("-", 1)[-1])
        if function_id == "claims.path.list":
            return ok_response({"claims": []})
        if function_id == "items.get.run":
            got = reads.handle_items_get(_items_get_request(item_id, ["db_mutation_profile"]))
            payloads[target.public_ref] = got.result_payload
            return SimpleNamespace(
                success=got.primary_success,
                result=got.result_payload,
                error=got.error,
            )
        if function_id == "shepherd.dependency_list.run":
            return ok_response({"item_id": item_id, "dependencies": []})
        raise AssertionError(function_id)

    candidate, err = candidate_shape(dispatch, "YOK-200")
    assert err is None
    context, ctx_err = train_context(dispatch, "YOK-200", ("YOK-150",))
    assert ctx_err is None
    assert "fields" in payloads["YOK-200"]
    assert "db_mutation_profile" not in payloads["YOK-200"]
    verdict = evaluate_admission(candidate, context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_MIGRATION_CARRIER


def test_queued_integration_branch_resolves_to_its_registered_item():
    fake = dispatch_for(
        {
            "YOK-200": {},
            "YOK-150": {"branch": "YOK-150-integration"},
        }
    )
    lane_reads = []

    def dispatch(**kwargs):
        if kwargs["function_id"] == DB_READ_FUNCTION_ID:
            lane_reads.append(kwargs["payload"]["sql"])
        return fake(**kwargs)

    context, err = train_context(
        dispatch,
        "YOK-200",
        ("YOK-150-integration",),
        "yoke",
    )

    assert err is None
    assert len(lane_reads) == 1
    assert "FROM item_worktrees" in lane_reads[0]
    assert "YOK-150-integration" in lane_reads[0]
    assert [member.public_ref for member in context.members] == ["YOK-150"]
    assert context.notes == ()


def test_unmapped_queued_branch_is_skipped_with_a_named_warning():
    context, err = train_context(
        dispatch_for({"YOK-200": {}}),
        "YOK-200",
        ("outside-yoke",),
        "yoke",
    )

    assert err is None
    assert context.members == ()
    assert len(context.notes) == 1
    assert "outside-yoke" in context.notes[0]
    assert "not a Yoke item" in context.notes[0]
