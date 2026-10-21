"""QA close-outs have fresh routes and bounded work on every dispatch."""

from yoke_core.domain import deployment_qa_member_acceptance_notice as notice


class _Conn:
    def commit(self):
        pass


def test_twelve_members_close_across_bounded_dispatches(monkeypatch):
    closed = set()
    reads = []
    clock = [0.0]

    def route(conn, *, run_id, item_id):
        reads.append((item_id, frozenset(closed)))
        return None if item_id in closed else ({"item_id": item_id}, True)

    def close(conn, *, item_id, route, **kwargs):
        assert route[0]["item_id"] == item_id
        closed.add(item_id)
        clock[0] += 3.0
        return "closed"

    monkeypatch.setattr(notice, "_withdraw_waits", lambda *a, **k: None)
    monkeypatch.setattr(notice, "_member_close_out_route", route)
    monkeypatch.setattr(notice, "_close_or_notify", close)
    monkeypatch.setattr(notice.time, "monotonic", lambda: clock[0])
    members = tuple(range(1, 13))
    for dispatch in range(6):
        before = clock[0]
        remaining = notice.notify_items_qa_accepted(_Conn(), run_id="run-sample", item_ids=members)
        assert len(closed) == 2 * (dispatch + 1)
        assert clock[0] - before == 6.0  # below the 30-second HTTPS limit
        assert remaining == members[len(closed):]
    assert [item for item, state in reads if item not in state] == list(members)
    assert all(set(range(1, item)) <= state for item, state in reads)


def test_slow_close_stops_starting_more_work(monkeypatch):
    clock = [0.0]
    acted = []
    monkeypatch.setattr(notice, "_withdraw_waits", lambda *a, **k: None)
    monkeypatch.setattr(notice, "_member_close_out_route", lambda *a, **k: ({}, True))
    monkeypatch.setattr(notice.time, "monotonic", lambda: clock[0])

    def close(conn, *, item_id, **kwargs):
        acted.append(item_id)
        clock[0] += 6.0
        return "closed"

    monkeypatch.setattr(notice, "_close_or_notify", close)
    assert notice.notify_items_qa_accepted(_Conn(), run_id="run-sample", item_ids=(1, 2, 3)) == (2, 3)
    assert acted == [1]
