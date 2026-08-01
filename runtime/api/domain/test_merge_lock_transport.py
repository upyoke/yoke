"""The merge lock works over a control plane the client cannot connect to.

A merging session on an https control plane has no local Postgres, so the
lock's row operations relay while holder liveness stays local — the process
holding a merge lock is the local merging process.
"""

from __future__ import annotations

import os

import pytest

from yoke_core.domain import merge_lock
from yoke_core.domain import merge_lock_contention as contention


class RelayLog(list):
    """The relayed calls, with the rows the control plane should serve."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []


@pytest.fixture
def relayed(monkeypatch: pytest.MonkeyPatch) -> RelayLog:
    """Capture relayed calls and serve canned rows."""
    log = RelayLog()

    def fake_relay(function_id: str, payload: dict) -> dict:
        log.append((function_id, dict(payload)))
        if function_id == "merge.lock.list":
            return {"rows": list(log.rows)}
        return {}

    monkeypatch.setattr(merge_lock, "_relay", fake_relay)
    monkeypatch.setattr(
        merge_lock, "_connect",
        lambda: pytest.fail("the lock must not open a local connection"),
    )
    return log


class TestCheck:
    def test_no_rows_means_no_blocking_holder(self, relayed) -> None:
        assert merge_lock.check() is None
        assert [call[0] for call in relayed] == ["merge.lock.list"]

    def test_a_live_holder_blocks_with_its_identity(self, relayed) -> None:
        relayed.rows.append({
            "id": 1,
            "session_id": f"{os.getpid()}-1700000000",
            "branch": "ITEM-1",
            "epic_id": "",
        })
        message = merge_lock.check()
        assert message is not None
        assert "ITEM-1" in message

    def test_an_epic_holder_names_its_epic(self, relayed) -> None:
        relayed.rows.append({
            "id": 1,
            "session_id": f"{os.getpid()}-1700000000",
            "branch": "ITEM-1",
            "epic_id": "42",
        })
        assert "(epic: 42)" in (merge_lock.check() or "")

    def test_a_dead_holder_is_retired_rather_than_blocking(
        self, relayed, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(contention, "holder_is_alive", lambda session_id: False)
        relayed.rows.append({
            "id": 7,
            "session_id": "999999-1700000000",
            "branch": "ITEM-1",
            "epic_id": "",
        })
        assert merge_lock.check() is None
        assert ("merge.lock.release", {"lock_ids": [7]}) in relayed

    def test_an_unparseable_holder_is_left_alone(self, relayed) -> None:
        """Without a usable pid the row is treated as live, never guessed away."""
        relayed.rows.append({
            "id": 3,
            "session_id": "not-a-pid",
            "branch": "ITEM-1",
            "epic_id": "",
        })
        assert merge_lock.check() is not None
        assert [call[0] for call in relayed] == ["merge.lock.list"]


class TestScope:
    """A merge contends only with merges landing on the same branch."""

    def _held(self, project: str | None, branch: str | None) -> dict:
        return {
            "id": 1,
            "session_id": f"{os.getpid()}-1700000000",
            "branch": "OTHER-9",
            "epic_id": "",
            "project_slug": project,
            "target_branch": branch,
        }

    def test_another_project_does_not_block(self, relayed) -> None:
        relayed.rows.append(self._held("acme", "main"))
        scope = merge_lock.LockScope("yoke", "main")
        assert merge_lock.check(scope=scope) is None

    def test_another_target_branch_does_not_block(self, relayed) -> None:
        relayed.rows.append(self._held("yoke", "release"))
        scope = merge_lock.LockScope("yoke", "main")
        assert merge_lock.check(scope=scope) is None

    def test_the_same_project_and_branch_blocks(self, relayed) -> None:
        relayed.rows.append(self._held("yoke", "main"))
        scope = merge_lock.LockScope("yoke", "main")
        assert merge_lock.check(scope=scope) is not None

    def test_an_unscoped_row_blocks_everything(self, relayed) -> None:
        """A legacy row's scope is unknown, which is not the same as compatible."""
        relayed.rows.append(self._held(None, None))
        scope = merge_lock.LockScope("yoke", "main")
        assert merge_lock.check(scope=scope) is not None

    def test_an_unscoped_caller_is_blocked_by_everything(self, relayed) -> None:
        relayed.rows.append(self._held("acme", "release"))
        assert merge_lock.check() is not None

    def test_a_non_contending_dead_holder_is_left_for_its_own_scope(
        self, relayed, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Out-of-scope rows are never retired here — they are not ours to judge."""
        monkeypatch.setattr(contention, "holder_is_alive", lambda session_id: False)
        relayed.rows.append(self._held("acme", "main"))
        assert merge_lock.check(scope=merge_lock.LockScope("yoke", "main")) is None
        assert [call[0] for call in relayed] == ["merge.lock.list"]

    def test_acquire_records_the_scope_it_took(self, relayed) -> None:
        scope = merge_lock.LockScope("acme", "release")
        handle = merge_lock.acquire("ITEM-1", scope=scope)
        _, payload = relayed[0]
        assert payload["project_slug"] == "acme"
        assert payload["target_branch"] == "release"
        assert handle.scope == scope


class TestAcquireAndRelease:
    def test_acquire_relays_the_row_and_returns_the_handle(self, relayed) -> None:
        handle = merge_lock.acquire("ITEM-1", "42")
        function_id, payload = relayed[0]
        assert function_id == "merge.lock.acquire"
        assert payload["branch"] == "ITEM-1"
        assert payload["epic_id"] == "42"
        assert payload["session_id"] == handle.session_id
        assert payload["acquired_at"] and payload["expires_at"]

    def test_acquire_still_refuses_an_empty_branch(self, relayed) -> None:
        with pytest.raises(ValueError):
            merge_lock.acquire("")
        assert relayed == []

    def test_release_relays_the_holder_identity(self, relayed) -> None:
        merge_lock.release(
            merge_lock.LockHandle(session_id="123-1700000000", branch="ITEM-1"),
        )
        assert relayed == [(
            "merge.lock.release",
            {"session_id": "123-1700000000", "branch": "ITEM-1"},
        )]

    def test_release_of_an_empty_handle_relays_nothing(self, relayed) -> None:
        merge_lock.release(merge_lock.LockHandle(session_id="", branch=""))
        assert relayed == []

    def test_force_clear_relays_a_whole_table_release(self, relayed) -> None:
        merge_lock.force_clear()
        assert relayed == [("merge.lock.release", {"all_rows": True})]


class TestRelayFailure:
    def test_a_refused_relay_raises_rather_than_merging_unlocked(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unavailable lock must stop the merge, never silently proceed."""
        from yoke_contracts.api.function_call import FunctionError

        class _Refused:
            success = False
            error = FunctionError(code="boom", message="control plane refused")
            result = None

        monkeypatch.setattr(
            "yoke_core.api.service_client_structured_api_adapter."
            "call_dispatcher",
            lambda **_kwargs: _Refused(),
        )
        with pytest.raises(RuntimeError, match="control plane refused"):
            merge_lock.check()
