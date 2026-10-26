"""Invite forms, one-time output, merged refs and serving-floor recovery."""

import json

import pytest

from runtime.api.cli.test_admission_commands import transport as _transport_fixture
from yoke_cli.commands import _helpers, registry
from yoke_cli.commands.adapters import teammate_invites as commands
from yoke_cli.commands.adapters.admission_floor_recovery import (
    ADMISSION_FLOOR_RECOVERY,
    admission_floor_hint,
)
from yoke_cli.config.local_reachability import LOCAL_REACHABILITY_NOTICE
from yoke_cli.manifest import build_manifest
from yoke_cli.product_boundary_teaching_sources import help_usage_recipes
from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_contracts.function_serving_floors import FUNCTION_MINIMUM_SERVING_VERSIONS

transport = _transport_fixture
ACTIONS = [
    (commands.invite, ["Ana"]),
    (commands.invites_list, []),
    (commands.invites_revoke, ["code-1"]),
    (commands.invites_reissue, ["code-1"]),
]
ROW = dict(
    invite_id=1,
    ref="code-1",
    kind="code",
    name="Ana",
    role="viewer",
    state="pending",
    expires_at="2030-01-02T00:00:00Z",
)
CODE = "yinv_" + "a" * 32


@pytest.fixture
def answers(transport, monkeypatch):
    monkeypatch.setattr(commands, "ensure_handlers_loaded", lambda: None)
    transport.form, transport.method = "name", "invite_code"
    transport.rows = [ROW]
    transport.email_rows = [
        dict(invite_id=1, email="ana@example.com", role=None, status="pending")
    ]
    transport.refusal, transport.hints = None, []
    real_call = commands.call_dispatcher

    def recording(**kwargs):
        transport.hints.append(kwargs)
        assert kwargs["_function_hint"] is admission_floor_hint
        return real_call(**kwargs)

    monkeypatch.setattr(commands, "call_dispatcher", recording)
    monkeypatch.setattr(_helpers, "call_dispatcher", recording)

    def answer(request):
        if transport.refusal:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code=transport.refusal, message="Correct company sign-in settings"
                ),
            )
        if request.function == "teammate_invites.list":
            result = dict(
                invite_form=transport.form,
                sign_in_method=transport.method,
                invites=transport.rows,
            )
        elif request.function == "identity.invite.list":
            result = {"invites": transport.email_rows}
        elif request.function == "identity.invite.create":
            result = {**transport.email_rows[0], **request.payload}
        elif request.function.endswith("revoke"):
            result = {"status": "revoked"}
        else:
            result = dict(
                invite=ROW,
                code=CODE,
                expires_at=ROW["expires_at"],
                guidance={
                    "send_to": "send it to Ana only, through a private channel",
                    "redeem_command": "yoke connect <origin>",
                    "redeem_instruction": "Choose Enter invite code",
                },
            )
        return HandlerOutcome(primary_success=True, result_payload=result)

    transport.handler = answer
    return transport


@pytest.mark.parametrize("method", ["invite_code", "company_sign_in", "yoke_account"])
@pytest.mark.parametrize("json_mode", [False, True])
def test_create_uses_server_form_and_carries_hint(answers, capsys, method, json_mode):
    name = method == "invite_code"
    answers.form, answers.method = ("name" if name else "email"), method
    person, function = (
        ("Ana", "teammate_invites") if name else ("ana@example.com", "identity.invite")
    )
    flags = ["--json"] if json_mode else []
    assert commands.invite([f" {person} ", "--role", "viewer", *flags]) == 0
    output = capsys.readouterr().out
    assert [c.function for c in answers.calls] == [
        "teammate_invites.list",
        f"{function}.create",
    ]
    assert answers.calls[-1].payload == {
        "name" if name else "email": person,
        "role": "viewer",
    }
    assert all(
        c.actor.session_id == "" and c.target.kind == "global" for c in answers.calls
    )
    assert len(answers.hints) == 2
    assert output.count(CODE) == int(name)
    if json_mode:
        assert json.loads(output)["success"] is True
    elif name:
        for text in (
            "shown once",
            "organization scope",
            "works once",
            "private channel",
            "yoke connect",
            "Enter invite code",
            "yoke invites reissue code-1",
        ):
            assert text in output
    else:
        assert "email-1" in output and "sign in" in output


@pytest.mark.parametrize(
    "form,method,person,error",
    [
        ("email", "company_sign_in", "Ana", "invite_email_required"),
        ("name", "invite_code", "ana@example.com", "invite_name_required"),
        ("local", "local", "Ana", "invite_local_universe"),
    ],
)
def test_shape_refusals_do_not_write(answers, capsys, form, method, person, error):
    answers.form, answers.method = form, method
    assert commands.invite([person, "--json"]) == 1
    result = json.loads(capsys.readouterr().out)["error"]
    assert result["code"] == error
    message = LOCAL_REACHABILITY_NOTICE if form == "local" else method.replace("_", " ")
    assert message in result["message"] and len(answers.calls) == 1


@pytest.mark.parametrize("include_used", [False, True])
def test_list_merges_refs_and_states_without_secrets(answers, capsys, include_used):
    answers.form = "email"
    states = ["pending", "expired", "revoked", "consumed"]
    answers.rows = [
        dict(ROW, state=s, ref=f"code-{n}") for n, s in enumerate(states, 1)
    ]
    answers.email_rows += [dict(answers.email_rows[0], invite_id=2, status="accepted")]
    flags = ["--include-used"] if include_used else []
    assert commands.invites_list(["--json", *flags]) == 0
    output = capsys.readouterr().out
    rows = json.loads(output)["result"]["invites"]
    expected = ["pending", "expired", "revoked", "joined", "pending", "joined"]
    assert [r["state"] for r in rows] == [
        s for s in expected if include_used or s != "joined"
    ]
    assert {"code-1", "email-1"} <= {r["ref"] for r in rows}
    assert CODE not in output and "code_hash" not in output
    assert [c.function for c in answers.calls] == [
        "teammate_invites.list",
        "identity.invite.list",
    ]
    assert answers.calls[0].payload == {"include_used": True}
    assert commands.invites_list(flags) == 0
    assert "Kind" in capsys.readouterr().out and len(answers.hints) == 4


@pytest.mark.parametrize(
    "adapter,ref,function",
    [
        (commands.invites_revoke, "code-1", "teammate_invites.revoke"),
        (commands.invites_revoke, "email-1", "identity.invite.revoke"),
        (commands.invites_reissue, "code-1", "teammate_invites.reissue"),
    ],
)
def test_management_routes_ref_with_hint(answers, capsys, adapter, ref, function):
    assert adapter([ref, "--json"]) == 0
    assert answers.calls[-1].function == function
    assert answers.calls[-1].payload == {"invite_id": 1}
    assert len(answers.hints) == 2
    assert capsys.readouterr().out.count(CODE) == int(function.endswith("reissue"))


def test_email_reissue_requires_revoke_and_create(answers, capsys):
    assert commands.invites_reissue(["email-1", "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "invite_reissue_email"
    assert "Revoke" in error["message"] and "yoke invite EMAIL" in error["message"]
    assert len(answers.calls) == 1


@pytest.mark.parametrize("adapter,args", ACTIONS)
def test_missing_form_refuses_without_fallback(
    answers, capsys, monkeypatch, adapter, args
):
    answers.missing = "teammate_invites.list"
    monkeypatch.setitem(
        FUNCTION_MINIMUM_SERVING_VERSIONS, answers.missing, "next-release"
    )
    assert adapter([*args, "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "function_version_skew"
    assert "minimum serving version next-release" in error["message"]
    assert error["recovery_hint"].endswith(ADMISSION_FLOOR_RECOVERY)
    assert len(answers.calls) == len(answers.hints) == 1


def test_missing_email_list_keeps_second_read_floor_hint(answers, capsys):
    answers.form, answers.missing = "email", "identity.invite.list"
    assert commands.invites_list(["--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "function_version_skew"
    assert "identity.invite.list" in error["message"]
    assert error["recovery_hint"].endswith(ADMISSION_FLOOR_RECOVERY)
    assert len(answers.calls) == len(answers.hints) == 2


@pytest.mark.parametrize("adapter,args", ACTIONS)
def test_bad_oidc_pre_read_is_preserved(answers, capsys, adapter, args):
    answers.refusal = "oidc_misconfigured"
    assert adapter([*args, "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "oidc_misconfigured"
    assert error["message"] == "Correct company sign-in settings"
    assert len(answers.calls) == len(answers.hints) == 1


@pytest.mark.parametrize("ref", ["1", "code-0", "email--1", "code-x", "email-01"])
def test_bad_ref_is_usage_error_without_reads(answers, capsys, ref):
    assert commands.invites_revoke([ref]) == 2
    assert "code-N or email-N" in capsys.readouterr().err
    assert answers.calls == []


def test_invite_recipes_reach_manifest_and_teaching():
    catalog = build_manifest()
    manifest = {
        row["function_id"]: row
        for row in [*catalog["subcommands"], *catalog["aliases"]]
        if row["tokens"][0] in {"invite", "invites"}
    }
    assert set(manifest) == {
        key
        for key in commands.USAGE_BY_FUNCTION_ID
        if key.startswith("teammate_invites.")
    }
    for function_id, usage in commands.USAGE_BY_FUNCTION_ID.items():
        assert usage in help_usage_recipes()
        if function_id in manifest:
            assert manifest[function_id]["usage"] == usage
    for action in ("create", "list", "revoke"):
        assert ("identity", "invite", action) not in registry.SUBCOMMAND_REGISTRY
