"""Worktrees are named by the item's public ref, not the raw internal id.

Exercises the end-to-end path for an item whose ``items.id`` differs from its
``project_sequence``: the created worktree directory and branch must carry the
public ref (``PREFIX-{project_sequence}``), the raw internal id must never
appear as a directory name, and the recorded worktree must resolve back to the
correct internal id from its name.
"""

from __future__ import annotations

import os

from runtime.api.domain.test_worktree_create_multiworktree import _config_path
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.item_worktree_resolution import (
    resolve_item_id_by_worktree_name,
)
from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema
from yoke_core.domain.worktree import create_worktree
from yoke_core.domain.worktree_naming import worktree_name_for_item
from runtime.api.domain.worktree_test_helpers import pin_test_item_workflow


def test_worktree_named_by_public_ref_and_resolves_back(
    git_repo,
    yoke_db,
    monkeypatch,
):
    internal_id = 99244
    sequence = 4242  # deliberately unequal to the internal id
    public_ref = f"YOK-{sequence}"

    conn = connect_test_db(yoke_db)
    try:
        ensure_item_worktree_schema(conn)
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, project_id, project_sequence) "
            "VALUES (%s, 'Public ref worktree naming', 'refined-idea', 1, %s)",
            (internal_id, sequence),
        )
        pin_test_item_workflow(conn, internal_id, "blitz")
        conn.commit()
        # The single source of truth for the name is the public ref, not the
        # internal id.
        assert worktree_name_for_item(conn, internal_id) == public_ref
    finally:
        conn.close()

    monkeypatch.setenv("YOKE_SESSION_ID", "public-ref-lane-owner")

    result = create_worktree(
        internal_id,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )

    assert result.error is None, result.error
    assert result.worktrees[0].branch == public_ref
    assert result.worktrees[0].path.endswith(f"/.worktrees/{public_ref}")
    assert os.path.isdir(result.worktrees[0].path)
    # The raw internal id is never used as a worktree directory name.
    assert not os.path.isdir(
        os.path.join(str(git_repo), ".worktrees", f"YOK-{internal_id}")
    )

    conn = connect_test_db(yoke_db)
    try:
        # The recorded worktree resolves back to the correct internal id from
        # both its branch name and its directory basename.
        assert resolve_item_id_by_worktree_name(conn, public_ref) == internal_id
        assert (
            resolve_item_id_by_worktree_name(
                conn, os.path.basename(result.worktrees[0].path)
            )
            == internal_id
        )
        # A name shaped from the internal id must NOT resolve to this item —
        # the sequence and the id are distinct and only the sequence is used.
        assert resolve_item_id_by_worktree_name(conn, f"YOK-{internal_id}") is None
    finally:
        conn.close()


def test_reverse_lookup_resolves_legacy_internal_id_named_worktree(
    yoke_db,
):
    """A worktree recorded under the legacy YOK-{internal_id} scheme still
    resolves — existing worktrees are never renamed and must keep resolving."""
    from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree

    conn = connect_test_db(yoke_db)
    try:
        ensure_item_worktree_schema(conn)
        # id == project_sequence models an item created before the public-ref
        # cutover, whose worktree was named YOK-{internal_id}.
        insert_item(conn, id=99245, project_sequence=99245, workflow_id="issue")
        insert_item_worktree(
            conn,
            item_id=99245,
            branch="YOK-99245",
            path="/repo/.worktrees/YOK-99245",
            lane_role="implementation",
        )
        conn.commit()
        assert resolve_item_id_by_worktree_name(conn, "YOK-99245") == 99245
        # Path-basename lookup also resolves.
        assert (
            resolve_item_id_by_worktree_name(conn, "/repo/.worktrees/YOK-99245")
            == 99245
        )
        # Unknown names resolve to nothing rather than a wrong item.
        assert resolve_item_id_by_worktree_name(conn, "YOK-999999") is None
    finally:
        conn.close()
