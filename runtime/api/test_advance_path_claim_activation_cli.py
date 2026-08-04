"""Tests for the advance_path_claim_activation CLI entrypoint."""

from __future__ import annotations

from yoke_core.domain import advance_path_claim_activation as activation_mod
from yoke_core.domain.advance_path_claim_activation import (
    ActivationOutcome,
    ActivationResult,
)
from runtime.api.advance_path_claim_activation_cli_test_support import (
    fake_db,
    seed_item,
    stub_run,
)


def test_cli_activates_planned_claims(fake_db, monkeypatch, capsys):
    seed_item(fake_db, 9999, owner=42, source=None)
    result = ActivationResult(
        item_id=9999,
        actor_id=42,
        outcomes=[
            ActivationOutcome(
                claim_id=101,
                state_before="planned",
                state_after="active",
                commit_sha="deadbeefcafef00d00000007" + "0" * 16,
            )
        ],
    )
    stub = stub_run(monkeypatch, result=result)

    rc = activation_mod.main(["--item", "9999"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "activated=[101]" in captured.out
    assert captured.err == ""
    stub.assert_called_once()
    kwargs = stub.call_args.kwargs
    assert kwargs["item_id"] == 9999
    assert kwargs["actor_id"] == 42


def test_cli_accepts_a_public_ref(fake_db, monkeypatch, capsys):
    seed_item(fake_db, 5555, owner=None, source=17)
    stub_run(
        monkeypatch,
        result=ActivationResult(item_id=5555, actor_id=17, outcomes=[]),
    )

    rc = activation_mod.main(["--item", "YOK-5555"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "activated=[]" in captured.out


def test_cli_resolves_a_non_default_project_prefix(fake_db, monkeypatch, capsys):
    seed_item(
        fake_db,
        8801,
        owner=42,
        source=None,
        project_id=2,
        project_sequence=7,
    )
    stub_run(
        monkeypatch,
        result=ActivationResult(item_id=8801, actor_id=42, outcomes=[]),
    )

    rc = activation_mod.main(["--item", "BUZ-7"])

    assert rc == 0


def test_cli_reports_blocked_claim(fake_db, monkeypatch, capsys):
    seed_item(fake_db, 1234, owner=99, source=None)
    blocked = ActivationResult(
        item_id=1234,
        actor_id=99,
        outcomes=[
            ActivationOutcome(
                claim_id=33,
                state_before="blocked",
                state_after="blocked",
                error="blocked: claim 30",
            )
        ],
        blocked_errors=[
            "claim 33 is blocked: claim 30; resolve the upstream claim "
            "before activating"
        ],
    )
    stub_run(monkeypatch, result=blocked)

    rc = activation_mod.main(["--item", "1234"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "BLOCKED: claim 33 is blocked" in captured.err
    assert captured.out == ""


def test_cli_reports_diverged_refs(fake_db, monkeypatch, capsys):
    seed_item(fake_db, 4321, owner=8, source=None)
    diverged = ActivationResult(
        item_id=4321,
        actor_id=8,
        outcomes=[],
        diverged_error="origin/main and refs/heads/main have diverged",
    )
    stub_run(monkeypatch, result=diverged)

    rc = activation_mod.main(["--item", "4321"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "DIVERGED: origin/main and refs/heads/main have diverged" in (
        captured.err
    )


def test_cli_blocks_item_without_actor(fake_db, monkeypatch, capsys):
    seed_item(fake_db, 7777, owner=None, source=None)
    stub = stub_run(
        monkeypatch,
        result=ActivationResult(item_id=7777, actor_id=0, outcomes=[]),
    )

    rc = activation_mod.main(["--item", "7777"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "BLOCKED: item has no owner/source actor" in captured.err
    stub.assert_not_called()


def test_cli_returns_2_for_missing_item(fake_db, monkeypatch, capsys):
    stub_run(
        monkeypatch,
        result=ActivationResult(item_id=0, actor_id=0, outcomes=[]),
    )

    rc = activation_mod.main(["--item", "404"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "ERROR: item 404 not found" in captured.err


def test_cli_returns_2_for_invalid_item(fake_db, monkeypatch, capsys):
    rc = activation_mod.main(["--item", "not-a-number"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "ERROR: invalid --item value" in captured.err
