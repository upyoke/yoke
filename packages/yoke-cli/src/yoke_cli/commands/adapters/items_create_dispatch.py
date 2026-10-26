"""Prove spec acceptance before writing against a serving create operation."""

from __future__ import annotations

from yoke_cli.commands import _helpers
from yoke_cli.commands.adapters.item_flow_output import render_item_instruction_summary
from yoke_cli.transport.human_values import write_human
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import FunctionError, TargetRef
from yoke_contracts.function_serving_floors import declared_argument_floors


def _spec_floor_refusal(response, *, preview: bool = True):
    floor = declared_argument_floors("items.create", {"spec": "requested"})["spec"]
    reference = response.result.get("public_ref")
    identity = (
        reference
        or f"an item (receipt id {response.result.get('item_id', 'unavailable')})"
    )
    fact = (
        "No item was filed."
        if preview
        else f"Creation may have allocated {identity} without its spec. Do not repeat create."
    )
    recovery = (
        "Use the CLI release served by this environment and its filing help, "
        "or ask the control-plane operator for a release carrying items.create spec input."
    )
    if not preview and not reference:
        recovery += (
            " Ask the control-plane operator to resolve the receipt to its public item "
            "reference before repair. Do not infer a public ref from the returned id."
        )
    elif not preview:
        recovery += (
            f" Inspect with yoke items get {reference} spec. In a project harness, "
            f"claim that item and repair with yoke items structured-field replace {reference} "
            "--field spec --stdin. The receipt retains the available item identifiers."
        )
    return response.model_copy(
        update={
            "success": False,
            "result": {} if preview else response.result,
            "error": FunctionError(
                code="function_argument_version_skew",
                message=(
                    "items.create spec input requires minimum serving version "
                    f"{floor.minimum_serving_version}; the serving create operation "
                    f"did not attest spec acceptance. {fact}"
                ),
                recovery_hint=recovery,
            ),
        }
    )


def _write_create_receipt(response, stdout, _stderr):
    result = response.result
    stdout.write(
        render_item_instruction_summary(
            result.get("execution_instructions") or [], result.get("public_ref", "ITEM")
        )
    )
    write_human(
        {
            key: value
            for key, value in result.items()
            if key != "execution_instructions"
        },
        stdout,
    )


def dispatch_create(*, target: TargetRef, payload: dict, session_id, json_mode: bool):
    _helpers.ensure_handlers_loaded()
    actor = build_actor(session_id=session_id)
    # A preview proves the contract without a title-only write on an older server.
    proof = call_dispatcher(
        function_id="items.create",
        target=target,
        payload={**payload, "dry_run": True},
        actor=actor,
    )
    if proof.success and proof.result.get("spec_accepted") is not True:
        proof = _spec_floor_refusal(proof)
    elif (
        not proof.success
        and proof.error
        and "requires a nonblank instruction" in proof.error.message
    ):
        proof = _spec_floor_refusal(proof)
    if not proof.success or payload.get("dry_run"):
        return _helpers.emit_response(
            proof, json_mode=json_mode, human_writer=_write_create_receipt
        )

    def verify_receipt(response, _actor):
        if response.success and response.result.get("spec_accepted") is not True:
            return _spec_floor_refusal(response, preview=False)
        return response

    return _helpers.dispatch_and_emit(
        function_id="items.create",
        target=target,
        payload=payload,
        session_id=session_id,
        json_mode=json_mode,
        response_recovery=verify_receipt,
        human_writer=_write_create_receipt,
    )
