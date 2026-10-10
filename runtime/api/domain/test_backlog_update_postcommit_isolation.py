"""Committed status cleanup is isolated from advisory telemetry failures."""

from __future__ import annotations

from io import StringIO
from unittest.mock import Mock

from yoke_contracts.public_ref import unresolved_item_ref

import pytest

from yoke_core.domain import (
    item_status_transitions,
    path_claims_dependency_propagation,
    sessions_terminal_chain_checkpoint,
    settling_run_replay,
)
from yoke_core.domain.backlog_update_effects import (
    UpdateEffectReceipt,
    run_post_commit_update_effects,
)


@pytest.fixture(autouse=True)
def _isolate_run_continuation(monkeypatch) -> None:
    monkeypatch.setattr(
        settling_run_replay,
        "replay_settling_runs_for_item",
        lambda _conn, **_kwargs: None,
    )


def _terminal_receipt() -> UpdateEffectReceipt:
    return UpdateEffectReceipt(
        status_event=(72, "release", "done", "test"),
        session_id="origin",
        messages=(),
        path_claim_ids_to_propagate=(31, 32),
        terminal_holder_session_ids=("holder",),
    )


def test_telemetry_failure_cannot_skip_terminal_cleanup(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        sessions_terminal_chain_checkpoint,
        "close_terminal_item_sessions",
        lambda _conn, **kwargs: calls.append(("closeout", kwargs)),
    )
    monkeypatch.setattr(
        path_claims_dependency_propagation,
        "propagate_release_unblock",
        lambda _conn, *, released_claim_id, commit: calls.append(
            ("path", (released_claim_id, commit))
        ),
    )

    def fail_telemetry(**_kwargs):
        raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(
        item_status_transitions,
        "emit_item_status_change",
        fail_telemetry,
    )
    out = StringIO()
    run_post_commit_update_effects(
        Mock(),
        receipt=_terminal_receipt(),
        out=out,
    )

    assert calls == [
        (
            "closeout",
            {
                "item_id": 72,
                "terminal_status": "done",
                "holder_session_ids": ("holder",),
            },
        ),
        ("path", (31, True)),
        ("path", (32, True)),
    ]
    assert "status-change telemetry deferred" in out.getvalue()


def test_closeout_failure_cannot_skip_path_repair_or_telemetry(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def fail_closeout(*_args, **_kwargs):
        raise RuntimeError("session closeout unavailable")

    monkeypatch.setattr(
        sessions_terminal_chain_checkpoint,
        "close_terminal_item_sessions",
        fail_closeout,
    )
    monkeypatch.setattr(
        path_claims_dependency_propagation,
        "propagate_release_unblock",
        lambda _conn, *, released_claim_id, commit: calls.append(
            ("path", (released_claim_id, commit))
        ),
    )
    monkeypatch.setattr(
        item_status_transitions,
        "emit_item_status_change",
        lambda **_kwargs: calls.append(("telemetry", True)),
    )
    conn = Mock()
    out = StringIO()
    run_post_commit_update_effects(
        conn,
        receipt=_terminal_receipt(),
        out=out,
    )

    assert calls == [
        ("path", (31, True)),
        ("path", (32, True)),
        ("telemetry", True),
    ]
    conn.rollback.assert_called_once()
    assert "terminal session closeout deferred" in out.getvalue()


def test_continuation_failure_cannot_skip_terminal_cleanup(monkeypatch) -> None:
    calls = []

    def fail_discovery(conn, *, item_id):
        raise RuntimeError("settling-run discovery unavailable")

    monkeypatch.setattr(
        settling_run_replay, "replay_settling_runs_for_item", fail_discovery
    )
    monkeypatch.setattr(
        sessions_terminal_chain_checkpoint,
        "close_terminal_item_sessions",
        lambda _conn, **_kwargs: calls.append("closeout"),
    )
    monkeypatch.setattr(
        path_claims_dependency_propagation,
        "propagate_release_unblock",
        lambda _conn, **kwargs: calls.append(kwargs["released_claim_id"]),
    )
    monkeypatch.setattr(
        item_status_transitions,
        "emit_item_status_change",
        lambda **_kwargs: calls.append("telemetry"),
    )
    conn = Mock()
    out = StringIO()

    run_post_commit_update_effects(conn, receipt=_terminal_receipt(), out=out)

    assert calls == ["closeout", 31, 32, "telemetry"]
    conn.rollback.assert_called_once()
    assert (
        f"settling-run continuation deferred for item {unresolved_item_ref()}"
        in out.getvalue()
    )
    assert "item 72" not in out.getvalue()
    assert "read its completion run and re-drive it." in out.getvalue()
