"""A batched close-out never acts on a route read before an earlier close-out.

The dispatch reads every accepted member's close-out route in one pass.
Closing one member changes run state a later member's route reads, so the
remaining routes are read again after each applied close-out. A notice
writes nothing a route reads, so it does not cost another run-wide read.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import deployment_qa_member_acceptance_notice as notice


class _Conn:
    def commit(self) -> None:
        pass


def test_routes_are_read_again_only_after_an_applied_close_out(monkeypatch) -> None:
    reads: list[tuple[int, ...]] = []
    acted: list[tuple[int, Any]] = []
    outcomes = {1: "closed", 2: "delivered", 3: ""}

    def routes(conn, *, run_id, item_ids):
        reads.append(tuple(item_ids))
        return {item_id: (f"read-{len(reads)}", item_id) for item_id in item_ids}

    def close_or_notify(conn, *, run_id, item_id, route, now):
        acted.append((item_id, route[0]))
        return outcomes[item_id]

    monkeypatch.setattr(notice, "_withdraw_waits", lambda *a, **k: None)
    monkeypatch.setattr(notice, "_member_close_out_routes", routes)
    monkeypatch.setattr(notice, "_close_or_notify", close_or_notify)

    notice.notify_items_qa_accepted(_Conn(), run_id="run-sample", item_ids=(1, 2, 3))

    assert reads == [(1, 2, 3), (2, 3)]
    assert acted == [(1, "read-1"), (2, "read-2"), (3, "read-2")]
