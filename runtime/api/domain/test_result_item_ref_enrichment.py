"""Tests for outbound result ``item_id`` / ``item_ref`` enrichment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from yoke_core.domain.result_item_ref_enrichment import enrich_result_item_refs

_LOOKUP_TARGET = "yoke_core.domain.item_ref_render.render_item_ref_lookup"


def _prefix_lookup(prefix: str = "BUZ"):
    calls: list[list[int]] = []

    def factory(_conn: object, item_ids: object) -> object:
        calls.append([int(item_id) for item_id in item_ids])
        return lambda item_id: f"{prefix}-{int(item_id)}"

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


def test_enrich_adds_item_ref_beside_bare_item_id() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs({"item_id": 99, "claim_id": 1}, conn=conn)
    assert out["item_id"] == 99
    assert out["item_ref"] == "BUZ-99"
    assert out["claim_id"] == 1
    assert lookup.calls == [[99]]  # type: ignore[attr-defined]


def test_enrich_skips_when_item_ref_already_present() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs(
            {"item_id": 99, "item_ref": "YOK-42"},
            conn=conn,
        )
    assert out["item_ref"] == "YOK-42"
    assert lookup.calls == []  # type: ignore[attr-defined]


def test_enrich_skips_non_numeric_item_id() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs({"item_id": "YOK-42"}, conn=conn)
    assert "item_ref" not in out
    assert lookup.calls == []  # type: ignore[attr-defined]


def test_enrich_session_current_item_id_gains_ref() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup("PLAT")
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs(
            {"success": True, "session": {"current_item_id": 1950, "mode": "dash"}},
            conn=conn,
        )
    assert out["session"]["current_item_id"] == 1950
    assert out["session"]["current_item_ref"] == "PLAT-1950"


def test_enrich_nested_claim_scope_gains_item_ref() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs(
            {"holder": {"scope": {"item_id": 42}}},
            conn=conn,
        )
    assert out["holder"]["scope"]["item_id"] == 42
    assert out["holder"]["scope"]["item_ref"] == "BUZ-42"


def test_enrich_top_level_scope_gains_item_ref() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs(
            {"target_kind": "item", "scope": {"item_id": 42}},
            conn=conn,
        )
    assert out["scope"]["item_id"] == 42
    assert out["scope"]["item_ref"] == "BUZ-42"
    assert lookup.calls == [[42]]  # type: ignore[attr-defined]


def test_enrich_epic_task_scope_gains_epic_ref() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs(
            {"scope": {"epic_id": 833, "task_num": 5}},
            conn=conn,
        )
    assert out["scope"]["epic_id"] == 833
    assert out["scope"]["task_num"] == 5
    assert out["scope"]["epic_ref"] == "BUZ-833"


def test_enrich_list_of_scopes_gains_refs() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs(
            {"claims": [{"scope": {"item_id": 7}}, {"scope": {"item_id": 8}}]},
            conn=conn,
        )
    assert out["claims"][0]["scope"]["item_ref"] == "BUZ-7"
    assert out["claims"][1]["scope"]["item_ref"] == "BUZ-8"
    assert lookup.calls == [[7, 8]]  # type: ignore[attr-defined]


def test_enrich_resolves_duplicate_ids_once() -> None:
    conn = MagicMock()
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs(
            {
                "item_id": 42,
                "holder": {"scope": {"item_id": 42}},
            },
            conn=conn,
        )
    assert out["item_ref"] == "BUZ-42"
    assert out["holder"]["scope"]["item_ref"] == "BUZ-42"
    assert lookup.calls == [[42]]  # type: ignore[attr-defined]


def test_enrich_cycle_does_not_hang() -> None:
    conn = MagicMock()
    payload: dict[str, object] = {"item_id": 3}
    payload["self"] = payload
    lookup = _prefix_lookup()
    with patch(_LOOKUP_TARGET, side_effect=lookup):
        out = enrich_result_item_refs(payload, conn=conn)
    assert out["item_ref"] == "BUZ-3"


def test_enrich_without_conn_opens_and_closes() -> None:
    fake_conn = MagicMock()
    lookup = _prefix_lookup()
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=fake_conn,
        ),
        patch(_LOOKUP_TARGET, side_effect=lookup),
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
