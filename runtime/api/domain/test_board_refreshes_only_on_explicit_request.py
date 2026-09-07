"""The board is refreshed only by an explicit ``yoke board rebuild``.

Ordinary activity — item mutations, lifecycle transitions, structured-field
writes, merge close-out, epic-task status flips — must neither render the
board nor queue a deferred refresh. These are the surfaces that used to
carry an automatic trigger; each is asserted here so a reintroduced trigger
fails a test rather than silently costing every session a board render.
"""

from __future__ import annotations

import inspect

import pytest

from yoke_core.domain import (
    advance_skip_core,
    backlog,
    backlog_batch_update,
    backlog_close_op,
    backlog_create_op,
    backlog_rendering,
    backlog_structured_write_op,
    backlog_update_op,
    backlog_update_retry,
    item_field_transform,
    item_field_transform_sections,
    standalone_item_merge_cli,
    update_status,
    update_status_helpers,
)
from yoke_core.engines import (
    done_transition,
    done_transition_runtime,
    merge_worktree_post_helpers,
)


AUTOMATIC_REBUILD_ENTRYPOINTS = (
    backlog_rendering,
    backlog,
    update_status_helpers,
    done_transition,
    done_transition_runtime,
    merge_worktree_post_helpers,
)


@pytest.mark.parametrize("module", AUTOMATIC_REBUILD_ENTRYPOINTS)
def test_no_module_exposes_an_automatic_rebuild_helper(module) -> None:
    for name in (
        "_rebuild_board",
        "_maybe_rebuild_board",
        "_rebuild_board_direct",
        "_regenerate_views",
        "_regenerate_views_advisory",
    ):
        assert not hasattr(module, name), (
            f"{module.__name__}.{name} reintroduces an automatic board rebuild; "
            "the board refreshes only on an explicit `yoke board rebuild`."
        )


MUTATION_ENTRYPOINTS = (
    (backlog_create_op, "execute_create"),
    (backlog_update_op, "_execute_update_once"),
    (backlog_update_retry, "execute_update"),
    (backlog_batch_update, "execute_batch_update"),
    (backlog_close_op, "execute_close"),
    (backlog_structured_write_op, "execute_structured_write"),
    (item_field_transform, "append_addendum"),
    (item_field_transform_sections, "section_upsert"),
    (advance_skip_core, "_do_execute_update"),
    (update_status, "update_task_status"),
)


@pytest.mark.parametrize("module,func_name", MUTATION_ENTRYPOINTS)
def test_mutation_entrypoints_take_no_rebuild_parameter(module, func_name) -> None:
    """A mutation cannot be asked to rebuild the board, even opt-in.

    The parameter is what let callers hand the render cost to an ordinary
    write; removing it is what makes the removal structural.
    """
    params = inspect.signature(getattr(module, func_name)).parameters
    assert "rebuild_board" not in params
    assert "no_rebuild" not in params


def test_merge_close_out_does_not_rebuild(monkeypatch) -> None:
    """Standalone-item merge close-out never renders the board."""
    source = inspect.getsource(standalone_item_merge_cli)
    assert "rebuild" not in source.lower()
