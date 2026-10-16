"""Named item facts preserve classification across JSON transport."""

import json

from yoke_contracts.board.item_data import EpicStats, classify_item_rows


def test_named_item_facts_ignore_field_order_and_unrelated_additions():
    facts = {
        "title": "Scoped task",
        "workflow_id": "custom",
        "status": "building",
        "priority": "high",
        "frozen_int": 0,
        "blocked_int": 0,
        "numid": 17,
        "project_display": "Example",
        "updated_at": "2026-10-15T12:00:00Z",
        "project_slug": "example",
        "public_item_prefix": "EX",
        "project_sequence": 8,
        "status_glyph": "🔧",
        "status_bucket": "implementing",
        "merge_queue_enqueued_at": None,
        "merge_queue_landed_at": None,
        "generated_children": "epic_tasks",
    }
    stats = {17: EpicStats(task_count=3, progress="1/3 (33%)")}
    expected = classify_item_rows([facts], stats)
    transported = json.loads(json.dumps(dict(reversed(list(facts.items())))))
    transported["additional_fact"] = "does not affect this renderer"
    actual = classify_item_rows([transported], stats)
    assert actual == expected
    item = actual["active"][0]
    assert (item.id, item.progress, item.status_glyph) == ("EX-8", "1/3 (33%)", "🔧")
    assert item.updated_at.isoformat() == "2026-10-15T12:00:00+00:00"
