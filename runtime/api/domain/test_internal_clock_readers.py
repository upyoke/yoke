"""Internal clock readers preserve instants until their declared boundary."""

from datetime import timedelta, timezone
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import (
    deployment_run_composition_freeze as composition,
    scheduler_events,
    sessions_identity_read as identity,
    sessions_render_end_chain_pending as checkpoint,
    steering_scope_coverage as coverage,
)

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = parse_instant(WIRE)
CLOCKS = (
    INSTANT,
    INSTANT.astimezone(timezone(timedelta(hours=5, minutes=45))),
    "2026-10-09T20:45:00.123456+05:45",
)


class Connection:
    def __init__(self, row):
        self.row = row

    def execute(self, *args):
        return SimpleNamespace(fetchone=lambda: self.row)


@pytest.mark.parametrize("clock", CLOCKS + (None,))
def test_identity_and_release_readers_return_native_optional_instants(
    monkeypatch, clock
):
    from yoke_core.domain import sessions_queries_lookup

    monkeypatch.setattr(
        sessions_queries_lookup,
        "resolve_harness_capabilities",
        lambda *args: {"downstream_paths": ["opaque capability"]},
    )
    row = (
        "codex",
        "codex-cli",
        "opaque version",
        "machine",
        "openai",
        "model",
        "requested",
        "/tmp/workspace",
        "SENIOR",
        1,
        2,
        "wait",
        clock,
    )
    result = identity.resolve_session_identity(Connection(row), "sample")
    expected = None if clock is None else INSTANT
    assert result.ended_at == expected
    assert result.executor_version == "opaque version"
    assert (
        checkpoint.last_released_at(Connection({"released_at": clock}), "sample")
        == expected
    )


@pytest.mark.parametrize("clock", ("", "2026-10-09", "2026-10-09T15:00:00-00:00"))
def test_invalid_stored_reader_clock_refuses(monkeypatch, clock):
    from yoke_core.domain import sessions_queries_lookup

    monkeypatch.setattr(
        sessions_queries_lookup,
        "resolve_harness_capabilities",
        lambda *args: {"downstream_paths": []},
    )
    with pytest.raises(InvalidInstant):
        identity.resolve_session_identity(
            Connection(("sample",) * 12 + (clock,)), "sample"
        )
    with pytest.raises(InvalidInstant):
        checkpoint.last_released_at(Connection({"released_at": clock}), "sample")


def test_steering_order_uses_instants_then_claim_id_without_mutating_input():
    claims = [
        {
            "claim_id": 3,
            "scope": {"project_id": 1},
            "claimed_at": "2026-10-09T10:00:00.123456-05:00",
        },
        {"claim_id": 2, "scope": {"project_id": 1}, "claimed_at": INSTANT},
        {
            "claim_id": 1,
            "scope": {"project_id": 1},
            "claimed_at": "2026-10-09T20:45:00.123455+05:45",
        },
    ]
    result = coverage.covering_claims(None, {"project_id": 1}, claims=claims)
    assert [claim["claim_id"] for claim in result] == [1, 2, 3]
    assert claims[0]["claimed_at"] == "2026-10-09T10:00:00.123456-05:00"
    assert result[1]["claimed_at"] is INSTANT


@pytest.mark.parametrize("clock", (None, "", "2026-10-09", "2026-10-09T15:00:00-00:00"))
def test_missing_or_invalid_required_steering_clock_refuses(clock):
    with pytest.raises(InvalidInstant):
        coverage.covering_claims(
            None,
            {"project_id": 1},
            claims=[{"scope": {"project_id": 1}, "claim_id": 1, "claimed_at": clock}],
        )


@pytest.mark.parametrize("clock", CLOCKS)
def test_repeated_composition_reply_formats_only_native_clock(monkeypatch, clock):
    monkeypatch.setattr(composition, "requires_release_admission", lambda *args: True)
    monkeypatch.setattr(composition, "_require_schema", lambda *args: None)
    result = composition.freeze_run_composition(
        Connection(("flow", "opaque", clock, 1, "[]")), "run"
    )
    assert result == {"run_id": "run", "frozen_at": WIRE}


def test_absent_composition_has_null_clock(monkeypatch):
    monkeypatch.setattr(composition, "requires_release_admission", lambda *args: False)
    assert composition.freeze_run_composition(Connection(None), "run") == {
        "run_id": "run",
        "frozen_at": None,
        "legacy": True,
    }


@pytest.mark.parametrize("clock", ("", "2026-10-09", "2026-10-09T15:00:00-00:00"))
def test_invalid_repeated_composition_clock_refuses(monkeypatch, clock):
    monkeypatch.setattr(composition, "requires_release_admission", lambda *args: True)
    monkeypatch.setattr(composition, "_require_schema", lambda *args: None)
    with pytest.raises(InvalidInstant):
        composition.freeze_run_composition(
            Connection(("flow", "opaque", clock, 1, "[]")), "run"
        )


@pytest.mark.parametrize("clock", CLOCKS + (None,))
def test_chain_event_boundary_formats_optional_release_clock(monkeypatch, clock):
    from yoke_core.domain import events

    emitted = []
    monkeypatch.setattr(
        events, "emit_event", lambda *args, **kwargs: emitted.append(kwargs)
    )
    scheduler_events.emit_chain_end_deferred(
        session_id="sample",
        triggered_by="sample",
        checkpoint_step=1,
        max_chain_steps=3,
        handler_outcome="completed",
        chainable=True,
        last_release_at=clock,
    )
    assert len(emitted) == 1
    assert emitted[0]["context"]["last_release_at"] == (None if clock is None else WIRE)
    assert emitted[0]["context"]["triggered_by"] == "sample"
