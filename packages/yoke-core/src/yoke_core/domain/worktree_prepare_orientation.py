"""Where a prepared lane's code and tests live, and how to run one test.

A worker arriving in a fresh lane has to answer three questions before it
can do anything: where does this project's source live, where do its tests
live, and what command runs one of them. Left unanswered by the preparation
receipt, every worker answered them by guessing — inventing conventional
source roots, mirroring a test filename into an implementation path that
did not exist, and running a bare ``pytest`` that the project's own wrapper
was there to replace.

The project already declares both answers: package roots on its
``architecture_model``, and test roots as their own Project Structure
family. This composes them into the receipt, beside the exact focused-test
command, so orientation is read rather than guessed.

A project that declares neither still gets a receipt: the section says so
by naming the empty list, which is a different answer from a project whose
roots simply were not looked up.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.tools._source_pythonpath import FOCUSED_PYTEST_RUN_RECIPE


def lane_orientation(
    item_id: int,
    tree_root: str,
    project_id: str = "",
) -> Dict[str, Any]:
    """The receipt's orientation section for *item_id*'s lane at *tree_root*.

    A caller that already resolved the item's project passes it, because
    the package roots are the project's and re-reading the item to name it
    is a round trip nobody needs.

    Both root reads degrade to an empty list rather than failing
    preparation: a lane that exists is worth reporting even where the
    declarations behind it could not be read.
    """
    return {
        "package_roots": list(_package_roots(item_id, project_id)),
        "test_roots": list(_test_roots(tree_root)),
        "focused_test_command": FOCUSED_PYTEST_RUN_RECIPE,
    }


def _package_roots(item_id: int, project_id: str) -> tuple[str, ...]:
    """Declared ``architecture_model`` package roots for the item's project."""
    from yoke_core.domain.worktree_dirty_main_classify import (
        lane_source_root_prefixes,
    )

    try:
        return lane_source_root_prefixes(int(item_id), project_id)
    except Exception:  # noqa: BLE001 — orientation never blocks preparation
        return ()


def _test_roots(tree_root: str) -> tuple[str, ...]:
    """Declared ``test_roots`` attachments for the lane's own checkout."""
    if not tree_root:
        return ()
    from yoke_core.tools.impacted_project_test_roots import resolve_test_roots

    try:
        return tuple(root.rstrip("/") for root in resolve_test_roots(tree_root))
    except Exception:  # noqa: BLE001 — orientation never blocks preparation
        return ()


__all__ = ["lane_orientation"]
