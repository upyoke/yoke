"""``yoke machine`` flag adapters for the machine registry."""

from __future__ import annotations

import argparse
import json
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_config.machine_access import OFFERS_ENFORCEMENT_NOTE


MACHINE_REGISTER_USAGE = (
    "yoke machine register [--name NAME] "
    "[--access-mode owner_only|actors|project_role|universe] "
    "[--session-id S] [--json]"
)
MACHINE_LIST_USAGE = "yoke machine list [--mine] [--session-id S] [--json]"
MACHINE_SHOW_USAGE = "yoke machine show [MACHINE-ID] [--session-id S] [--json]"
MACHINE_DETAIL_USAGE = "yoke machine detail [MACHINE-ID] [--session-id S] [--json]"
MACHINE_RETIRE_USAGE = (
    "yoke machine retire [MACHINE-ID] --confirm [--session-id S] [--json]"
)
MACHINE_SETTINGS_GET_USAGE = (
    "yoke machine settings get [MACHINE-ID] [--path use.mode] [--session-id S] [--json]"
)
MACHINE_SETTINGS_SET_USAGE = (
    "yoke machine settings set [MACHINE-ID] --path use.mode --value '\"universe\"' "
    "[--session-id S] [--json]"
)
USAGE_BY_FUNCTION_ID = {
    "machine.register": MACHINE_REGISTER_USAGE,
    "machine.list": MACHINE_LIST_USAGE,
    "machine.show": MACHINE_SHOW_USAGE,
    "machine.detail": MACHINE_DETAIL_USAGE,
    "machine.retire": MACHINE_RETIRE_USAGE,
    "machine.settings.get": MACHINE_SETTINGS_GET_USAGE,
    "machine.settings.set": MACHINE_SETTINGS_SET_USAGE,
}


def _local_machine_id() -> str:
    """The id this host asserts, which registration turns into a proved one."""
    from yoke_contracts.machine_config.runtime import machine_id

    resolved = machine_id()
    if not resolved:
        raise SystemExit(
            "this machine has no canonical machine id in ~/.yoke/config.json. "
            "Recovery: run `yoke onboard` (or `yoke status`) to complete machine "
            "setup, which assigns it."
        )
    return resolved


def _resolved_machine_id(explicit: str | None) -> str:
    return str(explicit).strip() if explicit else _local_machine_id()


def machine_register(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke machine register",
        description=(
            "Register this machine so the control plane knows the id it "
            "claims, who owns it, and which actors may spend its capacity."
        ),
    )
    parser.add_argument("--name", default=None)
    parser.add_argument("--access-mode", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MACHINE_REGISTER_USAGE)
    if parsed is None:
        return 2
    from yoke_contracts.machine_config.machine_name import machine_display_name

    machine_id = _local_machine_id()
    payload: dict[str, Any] = {
        "machine_id": machine_id,
        "name": parsed.name or machine_display_name(),
    }
    if parsed.access_mode:
        payload["access"] = {"use": {"mode": parsed.access_mode}}
    return dispatch_and_emit(
        function_id="machine.register",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        response_recovery=_store_rotated_machine_credential,
    )


def _store_rotated_machine_credential(response, _actor):
    if not getattr(response, "success", False):
        return response
    from yoke_cli.config.machine_registration import _persist_credential

    failure = _persist_credential(getattr(response, "result", None) or {}, None)
    if failure is None:
        result = dict(getattr(response, "result", None) or {})
        result["credential"] = {"status": "stored"}
        return response.model_copy(update={"result": result})
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

    return FunctionCallResponse(
        success=False,
        function=response.function,
        version=response.version,
        request_id=response.request_id,
        error=FunctionError(code="machine_credential_store_failed", message=failure),
    )


def machine_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke machine list",
        description="List the machines registered in this control plane.",
    )
    parser.add_argument("--mine", action="store_true", help="only machines you own")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MACHINE_LIST_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="machine.list",
        target=TargetRef(kind="global"),
        payload={"owned_only": parsed.mine},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def machine_show(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke machine show",
        description=(
            "Show one registered machine; defaults to this machine. "
            f"{OFFERS_ENFORCEMENT_NOTE}"
        ),
    )
    parser.add_argument("machine_id", nargs="?", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MACHINE_SHOW_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="machine.show",
        target=TargetRef(kind="global"),
        payload={"machine_id": _resolved_machine_id(parsed.machine_id)},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def machine_detail(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke machine detail",
        description="Show machine identity, harness, project, session, and token facts.",
    )
    parser.add_argument("machine_id", nargs="?", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MACHINE_DETAIL_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="machine.detail",
        target=TargetRef(kind="global"),
        payload={"machine_id": _resolved_machine_id(parsed.machine_id)},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def machine_retire(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke machine retire",
        description=(
            "Retire a machine, revoke only its bound bearer, and preserve history. "
            "Reconnect later by running the installer for a new machine identity."
        ),
    )
    parser.add_argument("machine_id", nargs="?", default=None)
    parser.add_argument("--confirm", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MACHINE_RETIRE_USAGE)
    if parsed is None:
        return 2
    if not parsed.confirm:
        parser.error(
            "--confirm is required because retirement revokes this machine's bearer"
        )
    return dispatch_and_emit(
        function_id="machine.retire",
        target=TargetRef(kind="global"),
        payload={"machine_id": _resolved_machine_id(parsed.machine_id)},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def machine_settings_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke machine settings get",
        description=(
            "Read the machine's access document, or one dotted leaf of it "
            "(use.mode, use.actor_ids, use.project_id, use.role, "
            "offers.executor_surfaces, offers.models, offers.qa_host, "
            f"offers.deploys). {OFFERS_ENFORCEMENT_NOTE}"
        ),
    )
    parser.add_argument("machine_id", nargs="?", default=None)
    parser.add_argument("--path", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MACHINE_SETTINGS_GET_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="machine.settings.get",
        target=TargetRef(kind="global"),
        payload={
            "machine_id": _resolved_machine_id(parsed.machine_id),
            "path": parsed.path,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def machine_settings_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke machine settings set",
        description=(
            "Replace one dotted leaf of the machine's access document. The "
            "value is JSON, so a list is '[1,2]' and a string is '\"universe\"'. "
            "Only the machine's owner or an administrator may. "
            f"{OFFERS_ENFORCEMENT_NOTE}"
        ),
    )
    parser.add_argument("machine_id", nargs="?", default=None)
    parser.add_argument("--path", required=True)
    parser.add_argument("--value", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MACHINE_SETTINGS_SET_USAGE)
    if parsed is None:
        return 2
    try:
        value = json.loads(parsed.value)
    except ValueError:
        # A bare word is the common case for a mode or role name, so accept it
        # rather than making every operator quote a JSON string.
        value = parsed.value
    return dispatch_and_emit(
        function_id="machine.settings.set",
        target=TargetRef(kind="global"),
        payload={
            "machine_id": _resolved_machine_id(parsed.machine_id),
            "path": parsed.path,
            "value": value,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "MACHINE_LIST_USAGE",
    "MACHINE_DETAIL_USAGE",
    "MACHINE_REGISTER_USAGE",
    "MACHINE_RETIRE_USAGE",
    "MACHINE_SETTINGS_GET_USAGE",
    "MACHINE_SETTINGS_SET_USAGE",
    "MACHINE_SHOW_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "machine_list",
    "machine_detail",
    "machine_register",
    "machine_retire",
    "machine_settings_get",
    "machine_settings_set",
    "machine_show",
]
