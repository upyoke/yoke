"""Explicit QA registration deletion and local credential cleanup."""

import argparse

from yoke_contracts.api.function_call import FunctionError, TargetRef
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.config.capability_secrets import (
    MachineCapabilitySecretError,
    delete_machine_capability_secrets,
)

DELETE_USAGE = (
    "yoke test-machine delete --project P --test-machine NAME --confirm "
    "[--json] [--session-id S]"
)


def _cleanup(response, _actor):
    if not response.success:
        return response
    result = response.result
    try:
        delete_machine_capability_secrets(result["project"], result["capability_type"])
    except MachineCapabilitySecretError as exc:
        return response.model_copy(
            update={
                "success": False,
                "error": FunctionError(
                    code="test_machine_local_secret_cleanup_failed",
                    message=compose_refusal(
                        f"Registration deleted; {exc}",
                        recovery="remove the named local secret directory on this computer; "
                        "registration deletion already succeeded",
                    ),
                ),
            }
        )
    return response


def test_machine_delete(args):
    parser = argparse.ArgumentParser(
        prog="yoke test-machine delete",
        description="Delete a project's test machine settings, verification status and "
        "operation receipts, then remove this computer's named machine secrets. "
        "QA history stays readable; other computers keep their local secrets.",
    )
    parser.add_argument(
        "--project", required=True, help="Project that owns the registration."
    )
    parser.add_argument(
        "--test-machine", required=True, metavar="NAME", help="Machine to delete."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm removal of settings and history.",
    )
    add_json_arg(parser)
    add_session_arg(parser)
    parsed = parse_or_usage_error(parser, args, DELETE_USAGE)
    if parsed is None:
        return 2
    if not parsed.confirm:
        parser.error(
            "--confirm is required: deletion removes settings, verification status "
            "and operation receipts; rerun with --confirm"
        )
    return dispatch_and_emit(
        function_id="test_machine.delete",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "test_machine": parsed.test_machine},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        response_recovery=_cleanup,
    )


USAGE_BY_FUNCTION_ID = {"test_machine.delete": DELETE_USAGE}
