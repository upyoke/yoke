"""Merge close-out asks for a prepared release over the bound connection.

Ordinary HTTPS projects have no local Postgres. Continuation therefore relays
``deployment_runs.continue_for_item`` and keeps the public reference the merge
already holds. It must not open a database, invent an unresolved ref, or name
a db-admin retry.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import standalone_item_merge_release_continuation as release_flow
from yoke_core.engines.runs_continue_for_item import (
    OUTCOME_BOUND,
    OUTCOME_NONE,
    OUTCOME_WAITING,
)

PUBLIC_REF = "ITEM-7"
ITEM_ID = 7
LINEAGE = "a" * 40


def _relay_calls(monkeypatch):
    calls: list[tuple[str, dict, object]] = []

    def fake_relay(function_id, payload, target=None, **_k):
        calls.append((function_id, payload, target))
        return {"ok": True, "outcome": OUTCOME_NONE}

    monkeypatch.setattr(release_flow, "relay", fake_relay)
    return calls


def _forbid_local_authority(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("continuation must not open a control-plane database")

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", boom)
    monkeypatch.setattr(
        "yoke_core.engines.runs_continue_for_item.continue_for_item", boom,
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_identity_item_ref.item_ref_for_id", boom,
    )


class TestHttpsNoPreparedRun:
    def test_completes_quietly(self, monkeypatch):
        _forbid_local_authority(monkeypatch)
        calls = _relay_calls(monkeypatch)

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, public_ref=PUBLIC_REF,
        )

        assert fragment is None
        assert warning == ""
        assert calls == [
            (
                release_flow.CONTINUE_FUNCTION,
                {},
                TargetRef(kind="item", item_id=ITEM_ID, public_ref=PUBLIC_REF),
            )
        ]


class TestPreparedRunStillHandsOff:
    def test_waiting_for_pair_is_reported_without_a_warning(self, monkeypatch):
        _forbid_local_authority(monkeypatch)

        def fake_relay(_function_id, _payload, _target=None, **_k):
            return {
                "ok": True,
                "outcome": OUTCOME_WAITING,
                "run_id": "run-1",
                "waiting_on": ["ITEM-8"],
            }

        monkeypatch.setattr(release_flow, "relay", fake_relay)

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, public_ref=PUBLIC_REF,
        )

        assert warning == ""
        assert fragment == {
            "run_id": "run-1",
            "outcome": OUTCOME_WAITING,
            "waiting_on": ["ITEM-8"],
        }

    def test_bound_and_handed_off_keeps_authorization_fields(self, monkeypatch):
        _forbid_local_authority(monkeypatch)

        def fake_relay(_function_id, _payload, _target=None, **_k):
            return {
                "ok": True,
                "outcome": OUTCOME_BOUND,
                "run_id": "run-1",
                "release_lineage": LINEAGE,
                "handed_off_to": "session-holder",
                "message_id": "msg-1",
            }

        monkeypatch.setattr(release_flow, "relay", fake_relay)

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, public_ref=PUBLIC_REF,
        )

        assert warning == ""
        assert fragment == {
            "run_id": "run-1",
            "outcome": OUTCOME_BOUND,
            "release_lineage": LINEAGE,
            "handed_off_to": "session-holder",
            "message_id": "msg-1",
        }


class TestGenuineFailureStaysExplicit:
    def test_names_the_known_public_ref_and_not_a_failed_merge(self, monkeypatch):
        _forbid_local_authority(monkeypatch)
        monkeypatch.setattr(
            release_flow,
            "relay",
            lambda *_a, **_k: (_ for _ in ()).throw(
                RuntimeError("duplicate_prepared_run")
            ),
        )

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, public_ref=PUBLIC_REF,
        )

        assert fragment is None
        assert "duplicate_prepared_run" in warning
        assert PUBLIC_REF in warning
        assert "not a merge failure" in warning
        assert "The merge is complete" in warning
        assert f"yoke deployment-runs find-by-item {PUBLIC_REF}" in warning
        assert f"yoke deployment-runs continue-for-item {PUBLIC_REF}" in warning
        assert "unresolved" not in warning
        assert "db-admin" not in warning
        assert "local-postgres" not in warning
        assert "re-run this command" not in warning.lower()

    def test_missing_hand_off_resumes_continuation_not_the_merge(self, monkeypatch):
        _forbid_local_authority(monkeypatch)

        def fake_relay(_function_id, _payload, _target=None, **_k):
            return {
                "ok": True,
                "outcome": OUTCOME_BOUND,
                "run_id": "run-1",
                "release_lineage": LINEAGE,
                "handed_off_to": "session-holder",
                "message_id": None,
            }

        monkeypatch.setattr(release_flow, "relay", fake_relay)

        fragment, warning = release_flow.continue_prepared_release(
            item_id=ITEM_ID, public_ref=PUBLIC_REF,
        )

        assert fragment["run_id"] == "run-1"
        assert fragment["release_lineage"] == LINEAGE
        assert PUBLIC_REF in warning
        assert "continue-for-item" in warning
        assert "not delivered" in warning
        assert "re-run this command" not in warning.lower()
        assert "db-admin" not in warning
