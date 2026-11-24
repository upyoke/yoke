"""A takeover create says open walks carry and names each carried execution."""

from __future__ import annotations

from runtime.api.cli.test_deployment_run_create_idempotency_cli import _create

from yoke_contracts.deployment_itemless_teaching import OPEN_WALKS_CARRY

NEW, OLD = "run-20261121-020", "run-20261121-019"


def test_takeover_receipt_and_note_name_the_carried_executions() -> None:
    result = {
        "run_id": NEW,
        "idempotency_key": "k1",
        "supersedes_run_id": OLD,
        "carried_execution_ids": ["exec-a", "exec-b"],
    }
    rc, out, err, _captured = _create(result, "--idempotency-key", "k1")

    assert rc == 0, err
    assert "exec-a" in out and "exec-b" in out
    assert f"{NEW} took over {OLD}" in err
    assert OPEN_WALKS_CARRY in err
    assert "Carried open plan walks: exec-a, exec-b." in err


def test_a_server_without_carried_ids_says_none_carried() -> None:
    result = {"run_id": NEW, "idempotency_key": "k1", "supersedes_run_id": OLD}
    rc, _out, err, _captured = _create(result, "--idempotency-key", "k1")

    assert rc == 0, err
    assert OPEN_WALKS_CARRY in err
    assert "Carried open plan walks: none." in err


def test_create_help_teaches_the_carry() -> None:
    rc, out, _err, _captured = _create({}, "--help")

    assert rc == 0
    assert " ".join(OPEN_WALKS_CARRY.split()) in " ".join(out.split())
    assert "carried_execution_ids" in out
