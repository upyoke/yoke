"""Committed status cleanup is isolated from advisory telemetry failures."""

from __future__ import annotations

from io import StringIO
from unittest.mock import Mock

from yoke_core.domain import (
    item_status_transitions,
    path_claims_dependency_propagation,
    sessions_item_focus_release,
)
from yoke_core.domain.backlog_update_effects import (
    UpdateEffectReceipt,
    run_post_commit_update_effects,
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
        sessions_item_focus_release,
        "release_item_focus_for_sessions",
        lambda _conn, item_id, session_ids: calls.append(
            ("focus", (item_id, session_ids))
        ),
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
        ("focus", (72, ("holder",))),
        ("path", (31, True)),
        ("path", (32, True)),
    ]
    assert "status-change telemetry deferred" in out.getvalue()


def test_focus_failure_cannot_skip_path_repair_or_telemetry(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def fail_focus(*_args, **_kwargs):
        raise RuntimeError("focus unavailable")

    monkeypatch.setattr(
        sessions_item_focus_release,
        "release_item_focus_for_sessions",
        fail_focus,
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
    assert "terminal session focus cleanup deferred" in out.getvalue()
