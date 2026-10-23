"""Fail-loud reads of the ``test_machine`` field in test-machine responses.

Server-composed responses name a QA host under ``test_machine`` (one host)
or ``test_machines`` (a project's hosts). A server that predates those
response fields answers without them; reading such a response refuses
with a named reason instead of a ``KeyError`` or a guess from another key.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.transport.control_plane_payload import current_server_build

#: Refusal reason when a server response lacks a test-machine field.
TEST_MACHINE_RESPONSE_FIELD_MISSING = "test_machine_response_field_missing"

_RECOVERY = "run the Yoke CLI release that server serves, or update the server"


def missing_test_machine_field_refusal(*, function_id: str, field: str) -> str:
    """The two-line refusal naming the function, the field and the recovery."""
    build = current_server_build().name or "unknown"
    return (
        f"error: {TEST_MACHINE_RESPONSE_FIELD_MISSING}: {function_id} returned "
        f"no {field!r} field; the serving build ({build}) predates that "
        "response field.\n"
        f"recovery: {_RECOVERY}."
    )


def read_test_machine_field(
    payload: Mapping[str, Any] | None,
    *,
    function_id: str,
    field: str = "test_machine",
) -> Any:
    """Return ``payload[field]``, or exit with the named refusal when absent."""
    if payload is not None and field in payload:
        return payload[field]
    raise SystemExit(
        missing_test_machine_field_refusal(function_id=function_id, field=field)
    )


def recorded_test_machine(artifact_read: Mapping[str, Any]) -> Any:
    """The test machine named by a ``qa.artifact.read`` local-handle answer.

    Only answers carrying ``recorded_path`` name the host that recorded the
    bytes; every other disposition has no ``test_machine`` field.
    """
    if "recorded_path" not in artifact_read:
        return None
    return read_test_machine_field(artifact_read, function_id="qa.artifact.read")


__all__ = [
    "TEST_MACHINE_RESPONSE_FIELD_MISSING",
    "read_test_machine_field",
    "recorded_test_machine",
    "missing_test_machine_field_refusal",
]
