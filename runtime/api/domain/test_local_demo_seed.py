"""Tests for local-universe demo seed helpers."""

from __future__ import annotations


def test_demo_seed_next_step_is_non_paging(monkeypatch):
    from yoke_core.domain import local_demo_seed

    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return {"success": True, "item_id": 1, "item_ref": "LOC-1"}

    monkeypatch.setattr(local_demo_seed, "_local_human_actor_id", lambda: 3)
    monkeypatch.setattr(
        "yoke_core.domain.backlog_create_op.execute_create",
        fake_create,
    )

    report = local_demo_seed.seed_demo_items(project="my-project", count=1)

    assert report["ok"] is True
    assert report["next_step"] == (
        "run `yoke board rebuild --print --no-pager` in the project checkout"
    )
    assert calls[0]["project"] == "my-project"
    assert calls[0]["rebuild_board"] is False
