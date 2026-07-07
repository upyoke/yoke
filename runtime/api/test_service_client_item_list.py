from __future__ import annotations

from typing import Any

from yoke_core.api import service_client
from yoke_core.api import service_client_items_listing
from runtime.api.conftest import insert_item


def _seed_items_conn(conn: Any) -> Any:
    """Seed an authority-shaped items table on the shared Postgres fixture."""
    for item_id in range(1, 5):
        insert_item(
            conn,
            id=item_id,
            title=f"Item {item_id}",
            status="idea",
            priority="medium",
            type="issue",
            source="user",
            frozen=0,
            project="yoke",
        )
    return conn


def test_item_list_limit_caps_rows(monkeypatch, capsys, test_db) -> None:
    conn = _seed_items_conn(test_db)
    monkeypatch.setattr(service_client_items_listing, "_get_db_readonly", lambda: conn)

    rc = service_client.cmd_item_list(["--limit", "2"])

    assert rc == 0
    rows = capsys.readouterr().out.strip().splitlines()
    assert rows == [
        "1|Item 1|idea|medium|issue|user",
        "2|Item 2|idea|medium|issue|user",
    ]


def test_item_list_body_without_id_uses_hidden_row_id(monkeypatch, capsys, test_db) -> None:
    from yoke_core.domain import render_body

    conn = _seed_items_conn(test_db)
    monkeypatch.setattr(service_client_items_listing, "_get_db_readonly", lambda: conn)
    monkeypatch.setattr(
        render_body,
        "build_body",
        lambda _conn, item_id: f"rendered YOK-{item_id}",
    )

    rc = service_client.cmd_item_list(["--fields", "body", "--limit", "1"])

    assert rc == 0
    assert capsys.readouterr().out.strip() == "rendered YOK-1"


def test_item_list_rejects_invalid_limit(capsys) -> None:
    rc = service_client.cmd_item_list(["--limit", "0"])

    assert rc == 2
    assert "--limit must be a positive integer" in capsys.readouterr().err
