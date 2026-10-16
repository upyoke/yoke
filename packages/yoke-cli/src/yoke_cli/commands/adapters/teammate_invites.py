"""Invite teammates using the server's sign-in method and manage both kinds."""

import argparse
import re

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.admission_floor_recovery import admission_floor_hint
from yoke_cli.config.local_reachability import LOCAL_REACHABILITY_NOTICE
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import FunctionError, TargetRef

INVITE_USAGE = "yoke invite PERSON [--role ROLE] [--json]"
LIST_USAGE = "yoke invites list [--include-used] [--json]"
REVOKE_USAGE = "yoke invites revoke REF [--json]"
REISSUE_USAGE = "yoke invites reissue REF [--json]"
USAGE_BY_FUNCTION_ID = {
    "teammate_invites.create": INVITE_USAGE,
    "teammate_invites.list": LIST_USAGE,
    "teammate_invites.revoke": REVOKE_USAGE,
    "teammate_invites.reissue": REISSUE_USAGE,
    "identity.invite.create": INVITE_USAGE,
    "identity.invite.list": LIST_USAGE,
    "identity.invite.revoke": REVOKE_USAGE,
}


def _reference(value):
    match = re.fullmatch(r"(code|email)-([1-9][0-9]*)", value)
    if match is None:
        raise argparse.ArgumentTypeError("use code-N or email-N from yoke invites list")
    return match[1], int(match[2])


def _parse(args, action):
    parser = argparse.ArgumentParser(
        prog="yoke invite" if action == "create" else f"yoke invites {action}",
        description=(
            "Invite a teammate by name on a code server, or by email with company "
            "sign-in or a Yoke account. Codes are shown once and expire in 24 hours. "
            "Send the code privately; they run yoke connect <server> and choose "
            "Enter invite code. Lost it? Reissue its code-N ref. "
            "Email invites join through sign-in; revoke and invite again to resend."
        ),
    )
    if action == "create":
        parser.add_argument("person", help="Teammate's display name or email address")
        parser.add_argument(
            "--role", help="Person's organization role (server default)"
        )
    elif action == "list":
        parser.add_argument(
            "--include-used", action="store_true", help="Include joined invites"
        )
    else:
        parser.add_argument(
            "ref", type=_reference, help="code-N or email-N from the list"
        )
    add_json_arg(parser)
    add_session_arg(parser)
    return parse_or_usage_error(
        parser, args, USAGE_BY_FUNCTION_ID[f"teammate_invites.{action}"]
    )


def _read(parsed, function_id, payload):
    ensure_handlers_loaded()
    return call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(session_id=parsed.session_id),
        _function_hint=admission_floor_hint,
    )


def _refusal(response, code, message):
    return response.model_copy(
        update={
            "success": False,
            "result": None,
            "error": FunctionError(code=code, message=message),
        }
    )


def _fact(parsed):
    response = _read(
        parsed,
        "teammate_invites.list",
        {"include_used": getattr(parsed, "include_used", False)},
    )
    if not response.success:
        return response
    form = response.result.get("invite_form")
    method = response.result.get("sign_in_method")
    if form == "local":
        return _refusal(response, "invite_local_universe", LOCAL_REACHABILITY_NOTICE)
    if form not in {"email", "name"} or not method:
        return _refusal(
            response,
            "function_version_skew",
            "teammate_invites.list did not provide the invite form and sign-in method "
            "(minimum serving version next-release). "
            + admission_floor_hint(response.function),
        )
    return response


def _created(response, stdout, stderr):
    result = response.result
    if "code" not in result:
        print(
            f"Invited {result['email']} (email-{result['invite_id']}). They join when they sign in.",
            file=stdout,
        )
        return
    row = result["invite"]
    print(
        f"Invite for {row['name']} ({row['ref']}). Copy the code now; shown once:",
        file=stdout,
    )
    print(result["code"], file=stdout)
    print(
        f"Role: {row['role']} (organization scope). Expires {result['expires_at']}; works once.",
        file=stdout,
    )
    for guidance in result["guidance"].values():
        print(guidance, file=stdout)
    print(f"Lost it? Run yoke invites reissue {row['ref']}.", file=stdout)


def invite(args):
    parsed = _parse(args, "create")
    if parsed is None:
        return 2
    fact = _fact(parsed)
    if not fact.success:
        return emit_response(fact, json_mode=parsed.json_mode)
    form = fact.result["invite_form"]
    person = parsed.person.strip()
    method = fact.result["sign_in_method"].replace("_", " ")
    if (form == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+", person)) or (
        form == "name" and "@" in person
    ):
        code = "invite_email_required" if form == "email" else "invite_name_required"
        accepted = "email address" if form == "email" else "display name"
        return emit_response(
            _refusal(
                fact,
                code,
                f"This server uses {method}; enter their {accepted} instead.",
            ),
            json_mode=parsed.json_mode,
        )
    payload = {"email" if form == "email" else "name": person}
    if parsed.role is not None:
        payload["role"] = parsed.role
    return dispatch_and_emit(
        function_id="identity.invite.create"
        if form == "email"
        else "teammate_invites.create",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_created,
        function_hint=admission_floor_hint,
    )


def _listed(response, stdout, stderr):
    rows = response.result["invites"]
    if not rows:
        print("No invites yet.", file=stdout)
        return
    print("Ref\tPerson\tKind\tRole (organization)\tState\tExpires", file=stdout)
    for row in rows:
        print(
            f"{row['ref']}\t{row['name']}\t{row['kind']}\t{row.get('role') or '—'}\t{row['state']}\t{row.get('expires_at') or '—'}",
            file=stdout,
        )


def invites_list(args):
    parsed = _parse(args, "list")
    if parsed is None:
        return 2
    fact = _fact(parsed)
    if not fact.success:
        return emit_response(fact, json_mode=parsed.json_mode)
    rows = list(fact.result["invites"])
    if fact.result["invite_form"] == "email":
        email = _read(parsed, "identity.invite.list", {})
        if not email.success:
            return emit_response(email, json_mode=parsed.json_mode)
        rows += [
            dict(
                row,
                ref=f"email-{row['invite_id']}",
                kind="email",
                name=row["email"],
                state=row["status"],
            )
            for row in email.result["invites"]
        ]
    rows = [
        dict(
            row,
            state="joined"
            if row["state"] in {"consumed", "accepted"}
            else row["state"],
        )
        for row in rows
    ]
    if not parsed.include_used:
        rows = [row for row in rows if row["state"] != "joined"]
    result = fact.model_copy(update={"result": {**fact.result, "invites": rows}})
    return emit_response(result, json_mode=parsed.json_mode, human_writer=_listed)


def _manage(args, action):
    parsed = _parse(args, action)
    if parsed is None:
        return 2
    fact = _fact(parsed)
    if not fact.success:
        return emit_response(fact, json_mode=parsed.json_mode)
    kind, invite_id = parsed.ref
    if kind == "email" and action == "reissue":
        return emit_response(
            _refusal(
                fact,
                "invite_reissue_email",
                "Email invites cannot be reissued. Revoke the email-N ref, then run yoke invite EMAIL again.",
            ),
            json_mode=parsed.json_mode,
        )

    def revoked(response, stdout, stderr):
        print(f"Revoked {kind}-{invite_id}.", file=stdout)

    return dispatch_and_emit(
        function_id=f"{'identity.invite' if kind == 'email' else 'teammate_invites'}.{action}",
        target=TargetRef(kind="global"),
        payload={"invite_id": invite_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_created if action == "reissue" else revoked,
        function_hint=admission_floor_hint,
    )


def invites_revoke(args):
    return _manage(args, "revoke")


def invites_reissue(args):
    return _manage(args, "reissue")
