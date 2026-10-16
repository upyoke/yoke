# ruff: noqa: F811

"""Source bindings require the named item's live lane and matching claim."""

from contextlib import nullcontext
from pathlib import Path

import pytest

from runtime.api.domain.test_session_claimed_worktrees import (
    _seed_claim,
    _seed_epic_task,
    _seed_item,
    _worktree_path,
    conn,  # noqa: F401 - disposable authority fixture
)
from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
from yoke_core.domain import migration_apply as subject


@pytest.fixture
def source_lane(conn, monkeypatch):
    item_id = 801
    _seed_item(conn, item_id=item_id)
    _seed_epic_task(conn, epic_id=item_id, task_num=1, worktree="worker-schema")
    _seed_epic_task(conn, epic_id=item_id, task_num=2, worktree="worker-api")
    root = Path(_worktree_path("worker-schema"))
    root.mkdir(parents=True)
    monkeypatch.setenv(SOURCE_DEV_RUN_ROOT_ENV, str(root))
    monkeypatch.setattr(subject.db_helpers, "connect", lambda: nullcontext(conn))
    return item_id, root


@pytest.mark.parametrize("target_kind", ["item", "epic_task"])
def test_matching_item_or_task_claim_authorizes_exact_source(
    conn, source_lane, target_kind
):
    item_id, root = source_lane
    _seed_claim(
        conn,
        session_id="caller",
        target_kind=target_kind,
        item_id=item_id,
        epic_id=item_id,
        task_num=1,
    )
    assert subject._source_worktree_path(item_id, "caller") == root.resolve()


@pytest.mark.parametrize(
    "invalid",
    [
        "unregistered",
        "unrelated",
        "unclaimed",
        "released_claim",
        "released_lane",
        "inactive_lane",
        "sibling_task",
        "missing",
        "relative",
        "blank",
    ],
)
def test_invalid_binding_refuses_before_rehearsal(
    conn, source_lane, monkeypatch, invalid, capsys
):
    item_id, root = source_lane
    _seed_claim(
        conn,
        session_id="caller",
        target_kind="epic_task",
        epic_id=item_id,
        task_num=2 if invalid == "sibling_task" else 1,
    )
    if invalid == "unregistered":
        conn.execute("DELETE FROM item_worktrees WHERE path = %s", (str(root),))
    elif invalid == "unrelated":
        _seed_item(conn, item_id=item_id + 1)
        item_id += 1
    elif invalid == "unclaimed":
        conn.execute("UPDATE work_claims SET session_id = 'other-caller'")
    elif invalid == "released_claim":
        conn.execute("UPDATE work_claims SET released_at = CURRENT_TIMESTAMP")
    elif invalid == "released_lane":
        conn.execute("UPDATE item_worktrees SET released_at = CURRENT_TIMESTAMP")
    elif invalid == "inactive_lane":
        conn.execute("UPDATE item_worktrees SET state = 'released'")
    elif invalid == "missing":
        monkeypatch.setenv(SOURCE_DEV_RUN_ROOT_ENV, str(root / "missing"))
    elif invalid in {"relative", "blank"}:
        monkeypatch.setenv(
            SOURCE_DEV_RUN_ROOT_ENV, "worker-schema" if invalid == "relative" else ""
        )
    conn.commit()
    monkeypatch.setattr(subject, "_parse_item_argument", lambda _ref: item_id)
    monkeypatch.setattr(subject, "resolve_ambient_session_id", lambda: "caller")
    monkeypatch.setattr(
        subject,
        "rehearse",
        lambda *_a, **_kw: pytest.fail("invalid source must not reach rehearsal"),
    )

    assert subject.main(["rehearse", f"DEMO-{item_id}"]) == 1
    refusal = capsys.readouterr().err
    assert "rehearsal_source_lane_invalid" in refusal
    assert f"item_id={item_id}" in refusal
    assert "--session-id-filter caller" in refusal
    assert "dev run --lane <registered-path>" in refusal


def test_no_binding_retains_item_lane_default(monkeypatch):
    monkeypatch.delenv(SOURCE_DEV_RUN_ROOT_ENV, raising=False)
    monkeypatch.setattr(
        subject.db_helpers,
        "connect",
        lambda: pytest.fail("ordinary default must not need another lookup"),
    )
    assert subject._source_worktree_path(801, "caller") is None


def test_symlink_binding_is_compared_by_physical_root(conn, source_lane, monkeypatch):
    item_id, root = source_lane
    _seed_claim(conn, session_id="caller", target_kind="item", item_id=item_id)
    alias = root.parent / "selected-source"
    alias.symlink_to(root, target_is_directory=True)
    monkeypatch.setenv(SOURCE_DEV_RUN_ROOT_ENV, str(alias))
    assert subject._source_worktree_path(item_id, "caller") == root.resolve()
