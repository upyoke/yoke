"""Regression checks for merge generated file transport."""

from __future__ import annotations

from yoke_core.engines import merge_worktree_prepare_state as st

from runtime.api.engines.test_merge_worktree_prepare_transport import (
    MergeArgs as MergeArgs,
    MergeContext as MergeContext,
    TEST_ITEM_REF as TEST_ITEM_REF,
    _no_bare_db as _no_bare_db,
    _resp as _resp,
)


class TestExtractGeneratedFilesRelays:
    def test_relays_item_detail_get_and_parses_body(self, monkeypatch):
        body = (
            f"## Worktree: {TEST_ITEM_REF}\n"
            "### Generated files\n"
            "- gen/a.py\n"
            "- gen/b.py\n"
            "## Worktree: YOK-99\n"
            "- gen/other.py\n"
        )

        def fake(**kwargs):
            assert kwargs["function_id"] == "items.get.run"
            assert kwargs["target"].public_ref == TEST_ITEM_REF
            assert kwargs["payload"]["fields"] == ["body"]
            return _resp(
                "items.get.run", {"public_ref": TEST_ITEM_REF, "fields": {"body": body}}
            )

        monkeypatch.setattr(st, "call_dispatcher", fake)
        _no_bare_db(monkeypatch)

        ctx = MergeContext(args=MergeArgs(branch=TEST_ITEM_REF), epic_id=TEST_ITEM_REF)
        assert st.extract_generated_files(ctx) == ["gen/a.py", "gen/b.py"]

    def test_relay_refused_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            st,
            "call_dispatcher",
            lambda **_k: _resp("items.get.run", success=False),
        )
        _no_bare_db(monkeypatch)
        ctx = MergeContext(args=MergeArgs(branch=TEST_ITEM_REF), epic_id=TEST_ITEM_REF)
        assert st.extract_generated_files(ctx) == []
