"""Tests for outbound result ``item_id`` / ``item_ref`` enrichment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from yoke_core.domain.result_item_ref_enrichment import enrich_result_item_refs


def test_enrich_adds_item_ref_beside_bare_item_id() -> None:
    conn = MagicMock()
    with patch(
        "yoke_core.domain.project_identity.render_item_ref",
        return_value="BUZ-7",
    ) as render:
        out = enrich_result_item_refs({"item_id": 99, "claim_id": 1}, conn=conn)
    assert out["item_id"] == 99
    assert out["item_ref"] == "BUZ-7"
    assert out["claim_id"] == 1
    render.assert_called_once_with(conn, 99, required=False)


def test_enrich_skips_when_item_ref_already_present() -> None:
    conn = MagicMock()
    with patch(
        "yoke_core.domain.project_identity.render_item_ref",
    ) as render:
        out = enrich_result_item_refs(
            {"item_id": 99, "item_ref": "YOK-42"},
            conn=conn,
        )
    assert out["item_ref"] == "YOK-42"
    render.assert_not_called()


def test_enrich_skips_non_numeric_item_id() -> None:
    conn = MagicMock()
    with patch(
        "yoke_core.domain.project_identity.render_item_ref",
    ) as render:
        out = enrich_result_item_refs({"item_id": "YOK-42"}, conn=conn)
    assert "item_ref" not in out
    render.assert_not_called()


def test_enrich_session_current_item_id_gains_ref() -> None:
    conn = MagicMock()

    def _render(_conn: object, item_id: int, *, required: bool = False) -> str:
        del required
        return f"PLAT-{item_id}"

    with patch(
        "yoke_core.domain.project_identity.render_item_ref",
        side_effect=_render,
    ):
        out = enrich_result_item_refs(
            {"success": True, "session": {"current_item_id": 1950, "mode": "dash"}},
            conn=conn,
        )
    assert out["session"]["current_item_id"] == 1950
    assert out["session"]["current_item_ref"] == "PLAT-1950"


def test_enrich_without_conn_opens_and_closes() -> None:
    fake_conn = MagicMock()
    with patch(
        "yoke_core.domain.db_helpers.connect",
        return_value=fake_conn,
    ), patch(
        "yoke_core.domain.project_identity.render_item_ref",
        return_value="BUZ-3",
    ):
        out = enrich_result_item_refs({"item_id": 3})
    assert out["item_ref"] == "BUZ-3"
    fake_conn.close.assert_called_once()


def test_enrich_connection_failure_leaves_payload_unchanged() -> None:
    with patch(
        "yoke_core.domain.db_helpers.connect",
        side_effect=RuntimeError("no db"),
    ):
        out = enrich_result_item_refs({"item_id": 3})
    assert out == {"item_id": 3}
