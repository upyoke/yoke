"""Strategy clocks preserve native precision, CAS, and immutable snapshots."""

from datetime import timedelta
from hashlib import sha256

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import (
    strategy_docs,
    strategy_docs_create,
    strategy_docs_render,
    strategy_checkpoints,
)
from yoke_core.domain.strategy_doc_history import list_doc_revisions

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_strategy_clock_roundtrip_and_cas_are_timezone_independent(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(strategy_docs_create, "next_updated_at", lambda: STAMP)
    monkeypatch.setattr(
        strategy_docs, "utc_now", lambda: STAMP + timedelta(microseconds=1)
    )
    created = strategy_docs_create.create_doc(
        test_db,
        1,
        "CLOCK",
        "# CLOCK\n\nOriginal clock body.\n",
        None,
        summary="Native clocks",
        state="draft",
    )
    assert created["updated_at"] == "1969-12-31T23:59:59.123456Z"
    old = strategy_docs.get_doc(test_db, 1, "CLOCK")
    before = test_db.execute(
        "SELECT updated_at, content FROM strategy_docs WHERE project_id=1 AND slug='CLOCK'"
    ).fetchone()
    assert before[0] == STAMP
    unchanged = strategy_docs.replace_doc(
        test_db,
        1,
        "CLOCK",
        old["content"],
        None,
        base_updated_at="1970-01-01T05:29:59.123456+05:30",
    )
    assert unchanged["unchanged"]
    changed = strategy_docs.replace_doc(
        test_db,
        1,
        "CLOCK",
        old["content"] + "Updated body.\n",
        None,
        base_updated_at=old["updated_at"],
    )
    assert changed["updated_at"] == "1969-12-31T23:59:59.123457Z"
    with pytest.raises(strategy_docs.StrategyDocConflictError):
        strategy_docs.replace_doc(
            test_db,
            1,
            "CLOCK",
            old["content"] + "Stale body.\n",
            None,
            base_updated_at=old["updated_at"],
        )
    revisions = list_doc_revisions(test_db, 1, "CLOCK")
    assert [row["created_at"] for row in revisions] == [
        changed["updated_at"],
        created["updated_at"],
    ]
    original = test_db.execute(
        "SELECT content, content_sha256, created_at FROM strategy_doc_revisions WHERE project_id=1 AND slug='CLOCK' AND revision=1"
    ).fetchone()
    assert original[0] == before[1]
    assert original[1] == sha256(before[1].encode()).hexdigest()
    assert original[2] == STAMP
    rendered = strategy_docs_render.render_file_map(test_db, 1, ["CLOCK"])[0]
    assert rendered["updated_at"] == changed["updated_at"]
    assert changed["updated_at"] in rendered["file_text"]
    archived = strategy_docs.set_doc_archived(test_db, 1, "CLOCK", archived=True)
    assert archived["archived_at"] == changed["updated_at"]
    assert (
        strategy_docs.set_doc_archived(test_db, 1, "CLOCK", archived=False)[
            "archived_at"
        ]
        is None
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_strategy_checkpoint_keeps_native_anchor(test_db, monkeypatch, zone):
    monkeypatch.setattr(strategy_checkpoints, "utc_now", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    assert strategy_checkpoints.record_checkpoint(test_db, project=1, kind="strategize")
    assert strategy_checkpoints.latest_checkpoint_at(test_db, 1) == STAMP
