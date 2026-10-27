"""QA close-outs read fresh routes and stop only on the time budget."""

from yoke_core.domain import deployment_qa_member_acceptance_notice as notice


class _Conn:
    def commit(self):
        pass


def _patch(monkeypatch, route, close, clock):
    monkeypatch.setattr(notice, "_withdraw_waits", lambda *a, **k: None)
    monkeypatch.setattr(notice, "_member_close_out_route", route)
    monkeypatch.setattr(notice, "_close_or_notify", close)
    monkeypatch.setattr(notice.time, "monotonic", lambda: clock[0])


def test_each_route_is_read_after_the_previous_close_out(monkeypatch):
    closed = set()
    reads = []

    def route(conn, *, run_id, item_id):
        reads.append((item_id, frozenset(closed)))
        return None if item_id in closed else ({"item_id": item_id}, True)

    def close(conn, *, item_id, route, **kwargs):
        assert route[0]["item_id"] == item_id
        closed.add(item_id)
        return "closed"

    _patch(monkeypatch, route, close, [0.0])
    members = tuple(range(1, 13))
    notice.notify_items_qa_accepted(_Conn(), run_id="run-sample", item_ids=members)
    assert closed == set(members)
    assert reads == [(item, frozenset(range(1, item))) for item in members]


def test_refused_close_outs_never_stop_a_later_member(monkeypatch):
    refused = {1, 2}
    acted = []

    def close(conn, *, item_id, **kwargs):
        acted.append((item_id, "refused" if item_id in refused else "closed"))
        return "delivered" if item_id in refused else "closed"

    _patch(monkeypatch, lambda *a, **k: ({}, True), close, [0.0])
    notice.notify_items_qa_accepted(_Conn(), run_id="run-sample", item_ids=(1, 2, 3))
    assert acted == [(1, "refused"), (2, "refused"), (3, "closed")]


def test_slow_close_stops_starting_more_work(monkeypatch):
    clock = [0.0]
    acted = []

    def close(conn, *, item_id, **kwargs):
        acted.append(item_id)
        clock[0] += 6.0
        return "closed"

    _patch(monkeypatch, lambda *a, **k: ({}, True), close, clock)
    notice.notify_items_qa_accepted(_Conn(), run_id="run-sample", item_ids=(1, 2, 3))
    assert acted == [1]
