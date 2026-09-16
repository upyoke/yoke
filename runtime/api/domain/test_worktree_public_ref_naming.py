"""Worktrees are named by the item's public ref, not the raw internal id.

Exercises the end-to-end path for an item whose ``items.id`` differs from its
``project_sequence``: the created worktree directory and branch must carry the
public ref (``PREFIX-{project_sequence}``), the raw internal id must never
appear as a directory name, and the recorded worktree must resolve back to the
correct internal id from its name.
"""

from __future__ import annotations

import os

import pytest

from runtime.api.domain.test_worktree_create_multiworktree import _config_path
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.item_worktree_resolution import (
    resolve_item_id_by_worktree_name,
)
from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema
from yoke_core.domain.worktree import create_worktree
from yoke_core.domain.worktree_lane_plan import (
    resolve_worktree_lanes_for_item,
)
from yoke_core.domain.worktree_naming import (
    ItemWorktreeIdentityUnresolved,
    candidate_worktree_names,
    legacy_worktree_name,
    worktree_name_for_item,
)
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


def test_minting_refuses_when_no_identity_resolves(yoke_db):
    """An item with no identity row gets a refusal, not YOK-{items.id}.

    The number in such a name is the storage key, and it names whichever
    item owns it as a sequence — so the branch, the directory, and every
    later lookup would carry that claim.
    """
    unbacked_id = 99245

    conn = connect_test_db(yoke_db)
    try:
        with pytest.raises(ItemWorktreeIdentityUnresolved) as exc_info:
            worktree_name_for_item(conn, unbacked_id)
    finally:
        conn.close()

    message = str(exc_info.value)
    assert str(unbacked_id) not in message
    assert "items.id" not in message


def test_minting_refuses_without_a_connection():
    """No connection is no identity read, so there is nothing to name from."""
    with pytest.raises(ItemWorktreeIdentityUnresolved):
        worktree_name_for_item(None, 99246)


def test_lookup_still_offers_the_legacy_name_for_an_unbacked_item(yoke_db):
    """Recognising an existing lane is the direction that may still guess.

    Lanes created before public-ref naming are on disk under the legacy
    shape and are never renamed, so the candidate set keeps offering it even
    where minting refuses.
    """
    unbacked_id = 99247

    conn = connect_test_db(yoke_db)
    try:
        names = candidate_worktree_names(conn, unbacked_id)
    finally:
        conn.close()

    assert legacy_worktree_name(unbacked_id) in names


def test_lane_plan_refuses_rather_than_planning_an_invented_name(
    git_repo, yoke_db,
):
    """The degraded plan used to name a lane from the internal id."""
    with pytest.raises(ItemWorktreeIdentityUnresolved):
        resolve_worktree_lanes_for_item(
            99248, str(git_repo), ".worktrees", yoke_db,
        )


def test_create_reports_the_refusal_instead_of_creating_a_lane(
    git_repo, yoke_db, monkeypatch,
):
    """The refusal reaches the caller as a result, naming no branch."""
    monkeypatch.setenv("YOKE_SESSION_ID", "unbacked-lane-owner")

    result = create_worktree(
        99249,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )

    assert result.created is False
    assert result.error
    assert result.branch == ""
    assert "99249" not in (result.error or "")
