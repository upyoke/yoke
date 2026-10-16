"""Personal token commands through plain-terminal transport and real handlers."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.cli.test_admission_commands import transport as _transport_fixture
from yoke_cli.commands import registry
from yoke_cli.commands.adapters import tokens
from yoke_cli.commands.adapters.admission_floor_recovery import (
    ADMISSION_FLOOR_RECOVERY,
    admission_floor_hint,
)
from yoke_cli.manifest import build_manifest
from yoke_cli.product_boundary_teaching_sources import help_usage_recipes
from yoke_contracts.api.function_call import ActorContext
from yoke_contracts.function_serving_floors import FUNCTION_MINIMUM_SERVING_VERSIONS
from yoke_contracts.timestamps import temporal_wire
from yoke_core.api.service_client_structured_api_adapter_inventory_admission import (
    ADMISSION_ADAPTERS,
)
from yoke_core.domain.handlers import _register_profile
from yoke_core.domain.terminal_reachable_functions import TERMINAL_RECIPES

transport = _transport_fixture
COMMANDS = [
    (tokens.tokens_create, ["--name", "ci"], "profile.token.create", {"name": "ci"}),
    (tokens.tokens_list, [], "profile.get", {}),
    (tokens.tokens_revoke, ["7"], "profile.token.revoke", {"token_id": 7}),
]


@pytest.fixture()
def profile(test_db, transport):
    actor_id = test_db.execute(
        "SELECT id FROM actors WHERE kind='human' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    rows = {}
    _register_profile.register(
        SimpleNamespace(
            register=lambda fid, fn, *args, **kw: rows.update({fid: (fn, kw)})
        )
    )
    transport.results = []
    transport.request_id = None

    def bound_call(request):
        assert request.actor.session_id == ""
        assert request.actor.actor_id is None
        assert request.target.kind == "global"
        bound = request.model_copy(
            update={
                "actor": ActorContext(actor_id=str(actor_id), session_id=""),
                "request_id": transport.request_id or request.request_id,
            }
        )
        result = rows[request.function][0](bound)
        transport.results.append(result)
        return result

    transport.handler = bound_call
    return rows


@pytest.mark.parametrize("json_mode", [False, True])
def test_plain_terminal_creates_lists_and_revokes_own_token(
    test_db, transport, profile, capsys, json_mode
):
    flags = ["--json"] if json_mode else []
    _, _, adapter, args = registry.resolve(
        ["tokens", "create", "--name", " ci-release ", *flags]
    )
    assert adapter(args) == 0
    created = transport.results[-1].result_payload
    token_id, raw = created["token_id"], created["raw_token"]
    output = capsys.readouterr().out
    assert created["name"] == "ci-release" and len(raw) > 20
    assert output.count(raw) == 1
    if json_mode:
        assert json.loads(output)["result"] == created
    else:
        assert "Lost it? Revoke it and create a new one" in output

    _, _, adapter, args = registry.resolve(["tokens", "list", *flags])
    assert adapter(args) == 0
    listed = capsys.readouterr().out
    assert raw not in listed and "raw_token" not in listed
    assert "token_hash" not in listed
    metadata = next(
        row
        for row in temporal_wire(transport.results[-1].result_payload)["tokens"]
        if row["token_id"] == token_id
    )
    assert metadata["name"] == "ci-release" and metadata["status"] == "active"
    assert metadata["created_at"] and metadata["last_used_at"] is None
    if json_mode:
        assert metadata in json.loads(listed)["result"]["tokens"]
    else:
        assert "ID\tName\tCreated\tLast used\tStatus" in listed
        assert (
            f"{token_id}\tci-release\t{metadata['created_at']}\tnever\tactive" in listed
        )

    _, _, adapter, args = registry.resolve(["tokens", "revoke", str(token_id), *flags])
    assert adapter(args) == 0
    revoked = capsys.readouterr().out
    assert raw not in revoked
    if json_mode:
        assert json.loads(revoked)["result"]["status"] == "revoked"
    else:
        assert revoked.strip() == f"Revoked token {token_id}."
    assert (
        test_db.execute(
            "SELECT status FROM api_tokens WHERE id=%s", (token_id,)
        ).fetchone()[0]
        == "revoked"
    )
    assert [call.function for call in transport.calls] == [
        "profile.token.create",
        "profile.get",
        "profile.token.revoke",
    ]
    for function_id in tokens.USAGE_BY_FUNCTION_ID:
        metadata = profile[function_id][1]
        assert metadata["adapter_status"] == "live"
        assert metadata["ambient_session_required"] is False
        assert metadata["claim_required_kind"] is None
        assert metadata["target_kinds"] == ["global"]
    assert {"profile.token.create", "profile.token.revoke"} <= TERMINAL_RECIPES


@pytest.mark.parametrize("label", ["   ", "x" * 81])
def test_invalid_label_preserves_handler_refusal_without_minting(
    test_db, transport, profile, capsys, label
):
    before = test_db.execute("SELECT count(*) FROM api_tokens").fetchone()[0]
    assert tokens.tokens_create(["--name", label, "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "payload_invalid"
    assert error["message"] == "name must be 1-80 characters"
    assert test_db.execute("SELECT count(*) FROM api_tokens").fetchone()[0] == before


def test_replay_refuses_secret_redisplay_and_names_replacement(
    test_db, transport, profile, capsys
):
    transport.request_id = "9e278eb6-05b0-4afd-9ba5-c6ab656c5351"
    args = ["--name", "ci", "--json"]
    assert tokens.tokens_create(args) == 0
    raw = json.loads(capsys.readouterr().out)["result"]["raw_token"]
    assert tokens.tokens_create(args) == 1
    output = capsys.readouterr().out
    error = json.loads(output)["error"]
    assert error["code"] == "result_unavailable"
    assert "cannot be shown again" in error["message"]
    assert "yoke tokens list" in error["message"]
    assert "yoke tokens revoke TOKEN-ID" in error["message"]
    assert "create a new one" in error["message"]
    assert raw not in output
    assert (
        test_db.execute(
            "SELECT count(*) FROM api_tokens WHERE creation_request_id=%s",
            (transport.request_id,),
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("adapter,args,function_id,payload", COMMANDS)
def test_each_adapter_passes_admission_hint(
    monkeypatch, adapter, args, function_id, payload
):
    calls = []
    monkeypatch.setattr(tokens, "dispatch_and_emit", lambda **kw: calls.append(kw) or 0)
    assert adapter(args) == 0
    assert len(calls) == 1
    assert calls[0]["function_hint"] is admission_floor_hint
    assert calls[0]["function_id"] == function_id
    assert calls[0]["payload"] == payload
    assert calls[0]["target"].kind == "global"
    assert calls[0]["session_id"] is None


@pytest.mark.parametrize("adapter,args,function_id,payload", COMMANDS)
def test_missing_server_function_names_test_floor_and_recovery(
    monkeypatch, transport, capsys, adapter, args, function_id, payload
):
    assert function_id not in FUNCTION_MINIMUM_SERVING_VERSIONS
    monkeypatch.setitem(FUNCTION_MINIMUM_SERVING_VERSIONS, function_id, "next-release")
    transport.missing = function_id
    assert adapter([*args, "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "function_version_skew"
    assert "(minimum serving version next-release)" in error["message"]
    assert error["recovery_hint"].endswith(ADMISSION_FLOOR_RECOVERY)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("args", [["create"], ["revoke"], ["revoke", "bad-id"]])
def test_bad_usage_does_not_dispatch(transport, capsys, args):
    _, _, adapter, remaining = registry.resolve(["tokens", *args])
    assert adapter(remaining) == 2
    assert "yoke tokens" in capsys.readouterr().err
    assert transport.calls == []


def test_token_recipes_reach_inventory_manifest_and_teaching():
    inventory = {row.function_id: row.cli_invocation for row in ADMISSION_ADAPTERS}
    catalog = build_manifest()
    manifest = {
        row["function_id"]: row
        for row in [*catalog["subcommands"], *catalog["aliases"]]
        if row["tokens"][0] == "tokens"
    }
    assert set(manifest) == set(tokens.USAGE_BY_FUNCTION_ID)
    for function_id, usage in tokens.USAGE_BY_FUNCTION_ID.items():
        assert inventory[function_id] == manifest[function_id]["usage"] == usage
        assert usage in help_usage_recipes()
