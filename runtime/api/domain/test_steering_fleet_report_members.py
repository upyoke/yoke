"""Document seats see linked work from its execution project."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain.steering_fleet_report_members import read_seat_items


def test_document_seat_reads_cross_project_item_facts(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.steering_fleet_report_members.member_project_ids",
        lambda conn, ids: {2},
    )
    local = SimpleNamespace(item_id=11, session_id="local")
    linked = SimpleNamespace(item_id=22, session_id="linked")
    unrelated = SimpleNamespace(item_id=23, session_id="other")

    def facts(rows):
        return SimpleNamespace(
            **{field: rows for field in ("available", "holders", "landed_open")},
            **{field: rows for field in ("undelivered", "vendor_errors", "stranded")},
        )

    class Reads:
        def project_facts(self, conn, *, project_id, session_id, now):
            return facts((local,)) if project_id == 1 else facts((linked, unrelated))

    result = read_seat_items(
        object(),
        scope={"project_id": 1, "document": "RELEASES"},
        members={22},
        session_id="seat",
        now="now",
        reads=Reads(),
    )
    assert result.project_ids == (1, 2)
    assert result.available == (linked,)
    assert result.holders == (linked,)
    assert result.landed_open == (linked,)
    assert result.undelivered == (linked,)
    assert result.vendor_errors == (linked,)
