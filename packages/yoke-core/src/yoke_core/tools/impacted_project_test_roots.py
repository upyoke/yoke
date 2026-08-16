"""Resolve a checkout's Project Structure ``test_roots`` attachments.

Absence on a non-yoke checkout is a named verdict, never a silent
substitute of another project's anchors. A yoke-shaped tree whose live
read is missing or empty still uses the seeded triple so this checkout's
own suite does not depend on a deployed ``project_structure.get``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from yoke_contracts.project_defaults import default_project_for_directory
from yoke_core.tools._source_pythonpath import is_yoke_shaped_tree

UNSUPPORTED_PROJECT_TEST_ROOTS = "unsupported_project_test_roots"
YOKE_SEEDED_TEST_ROOTS = ("runtime/api/", "runtime/harness/", "tests/")
FAMILY = "test_roots"


@lru_cache(maxsize=8)
def resolve_test_roots(repo_root: str) -> tuple[str, ...]:
    """Declared test-root attachments for *repo_root*, or ``()``."""
    root = Path(repo_root)
    project = default_project_for_directory(root)
    live = _try_read(project)
    if live:
        return live
    if is_yoke_shaped_tree(root):
        return YOKE_SEEDED_TEST_ROOTS
    return ()


def default_testpaths(repo_root: Path) -> tuple[str, ...]:
    """Runner default paths: declared roots with trailing slashes stripped."""
    roots = resolve_test_roots(str(repo_root.resolve()))
    return tuple(root.rstrip("/") for root in roots)


def _try_read(project: str) -> tuple[str, ...] | None:
    from yoke_core.domain.control_plane_transport import relay

    try:
        result = relay(
            "project_structure.get",
            {"project_id": project, "family": FAMILY},
        )
    except Exception:  # noqa: BLE001 — missing get or relay failure
        return None
    if "entries" not in result:
        return None
    entries = result.get("entries") or []
    roots: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        attachment = str(entry.get("attachment") or "").strip()
        if not attachment:
            continue
        if not attachment.endswith("/"):
            attachment += "/"
        roots.append(attachment)
    return tuple(roots)


__all__ = [
    "FAMILY",
    "UNSUPPORTED_PROJECT_TEST_ROOTS",
    "YOKE_SEEDED_TEST_ROOTS",
    "default_testpaths",
    "resolve_test_roots",
]
