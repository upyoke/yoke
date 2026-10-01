# ruff: noqa: F811
"""Merge close-out observes an existing pin; explicit recovery retains its guard."""

from types import SimpleNamespace

from yoke_core.domain import deployment_runs_crud_mutate as mutate
from yoke_core.domain.deployment_run_lineage_rebind import lineage_of
from yoke_core.engines import runs_continue_for_item as continuation
from yoke_core.engines import runs_release_handoff as handoff
from runtime.api.test_prepared_release_continuation import (  # noqa: F401
    CONSUMER_ITEM,
    MERGE_COMMIT,
    OTHER_COMMIT,
    PRODUCER_ITEM,
    _conn,
    _mark_merged,
    db_path,
    prepared_run,
)


def _pin(db_path, run_id):
    assert (
        mutate.cmd_update(
            run_id,
            "release_lineage",
            MERGE_COMMIT,
            db_path=db_path,
        )
        is None
    )


def test_automatic_close_out_leaves_existing_pin_and_handoff_alone(
    db_path,
    prepared_run,
    monkeypatch,
):
    _pin(db_path, prepared_run)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("observing a pinned run must not prepare or hand it off")

    monkeypatch.setattr(continuation, "_merge_identity", forbidden)
    monkeypatch.setattr(continuation, "cmd_validate_composition", forbidden)
    monkeypatch.setattr(continuation, "refuse_lineage_write", forbidden)
    monkeypatch.setattr(handoff, "hand_off_prepared_run", forbidden)

    result = continuation.continue_for_item(
        PRODUCER_ITEM, session_id=None, db_path=db_path
    )

    assert result.ok
    assert result.outcome == continuation.OUTCOME_PINNED
    assert result.run_id == prepared_run
    assert result.release_lineage == MERGE_COMMIT
    assert result.message_id is None
    conn = _conn(db_path)
    try:
        assert lineage_of(conn, prepared_run) == MERGE_COMMIT
    finally:
        conn.close()


def test_explicit_handoff_recovery_keeps_the_pin(db_path, prepared_run, monkeypatch):
    _pin(db_path, prepared_run)
    _mark_merged(db_path, CONSUMER_ITEM)
    calls = []

    def recover(_conn, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(recipient="deploy-holder", message_id="handoff")

    monkeypatch.setattr(handoff, "hand_off_prepared_run", recover)
    result = continuation.continue_for_item(
        PRODUCER_ITEM,
        release_lineage=MERGE_COMMIT,
        session_id=None,
        db_path=db_path,
    )

    assert result.ok
    assert result.outcome == continuation.OUTCOME_BOUND
    assert calls[0]["release_lineage"] == MERGE_COMMIT


def test_explicit_different_lineage_still_refuses(db_path, prepared_run, monkeypatch):
    _pin(db_path, prepared_run)
    _mark_merged(db_path, CONSUMER_ITEM)
    monkeypatch.setattr(handoff, "hand_off_prepared_run", lambda *_a, **_k: None)

    result = continuation.continue_for_item(
        PRODUCER_ITEM,
        release_lineage=OTHER_COMMIT,
        session_id=None,
        db_path=db_path,
    )

    assert not result.ok
    assert result.error_code == "lineage_write_refused"
    assert MERGE_COMMIT in result.error and OTHER_COMMIT in result.error


def test_unbound_run_still_binds_recorded_merge(db_path, prepared_run, monkeypatch):
    _mark_merged(db_path, CONSUMER_ITEM)
    monkeypatch.setattr(continuation, "_merge_identity", lambda *_a: OTHER_COMMIT)
    monkeypatch.setattr(
        handoff,
        "hand_off_prepared_run",
        lambda *_a, **_k: SimpleNamespace(
            recipient="deploy-holder", message_id="handoff"
        ),
    )

    result = continuation.continue_for_item(
        PRODUCER_ITEM, session_id=None, db_path=db_path
    )

    assert result.ok
    assert result.outcome == continuation.OUTCOME_BOUND
    assert result.release_lineage == OTHER_COMMIT


def test_pair_summary_reports_new_handoff_alongside_existing_pin():
    result = continuation._aggregate(
        [
            continuation.ContinueResult(
                ok=True,
                outcome=continuation.OUTCOME_PINNED,
                run_id="stage",
                release_lineage=MERGE_COMMIT,
            ),
            continuation.ContinueResult(
                ok=True,
                outcome=continuation.OUTCOME_BOUND,
                run_id="production",
                release_lineage=MERGE_COMMIT,
                message_id="handoff",
            ),
        ]
    )

    assert result.outcome == continuation.OUTCOME_BOUND
    assert result.run_id == "production"
    assert [run["outcome"] for run in result.runs] == [
        continuation.OUTCOME_PINNED,
        continuation.OUTCOME_BOUND,
    ]
