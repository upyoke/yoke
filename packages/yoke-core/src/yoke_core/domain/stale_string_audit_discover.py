"""Test-surface discovery for the stale-string audit gate.

Owns:

* ``discover_test_surfaces(item_id)`` — resolve the project's test surfaces
  via the ``context_routing`` Project Structure family (topic ``testing``),
  ``command_definitions`` (e2e + smoke), deterministic directory scans, and
  built-in defaults.
* Surface-discovery internal helpers: ``_extract_test_dirs_from_docs``,
  ``_extract_dirs_from_test_command``, ``_looks_like_test_surface``,
  ``_scan_test_directories``.
* Item / project lookup helpers: ``_get_project_for_item``,
  ``_get_item_field``, ``_get_project_field``, ``_normalize_item_id``.

Candidate-string extraction lives in ``stale_string_audit_extract``.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from yoke_core.domain._stale_string_audit_constants import DEFAULT_TEST_DIRS


# ── Item / project lookup helpers ───────────────────────────────────────


def _normalize_item_id(raw: str) -> Optional[int]:
    stripped = raw.strip()
    if stripped.upper().startswith("YOK-"):
        stripped = stripped[4:]
    stripped = stripped.lstrip("0")
    if stripped == "":
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _get_project_for_item(item_id: int) -> Optional[str]:
    """Return the project ID for *item_id*, or None."""
    try:
        from yoke_core.domain import db_backend, db_helpers
        with db_helpers.connect() as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = db_helpers.query_one(
                conn,
                "SELECT p.slug AS project FROM items i "
                "LEFT JOIN projects p ON p.id = i.project_id "
                f"WHERE i.id = {p}",
                (item_id,),
            )
            if row:
                return row["project"] or None
    except Exception:
        pass
    return None


def _get_item_field(item_id: int, field: str) -> str:
    """Return a rendered item field value or an empty string."""
    try:
        from yoke_core.domain.items import query_item

        return query_item(item_id, field).strip()
    except Exception:
        return ""


def _get_project_field(project_id: str, field: str) -> Optional[str]:
    """Return a single field from the projects table."""
    try:
        from yoke_core.domain import db_helpers
        with db_helpers.connect() as conn:
            row = db_helpers.query_one(
                conn, f"SELECT {field} FROM projects WHERE id = ?", (project_id,),
            )
            if row:
                val = row[field]
                if val and val != "null":
                    return val
    except Exception:
        pass
    return None


# ── Test surface discovery ──────────────────────────────────────────────


def discover_test_surfaces(item_id: int) -> Dict[str, Any]:
    """Discover test surfaces for an item's project.

    Returns a dict::

        {
            "project": "buzz",
            "checkout_path": "/path/to/buzz",
            "surfaces": ["e2e/", "__tests__/", ...],
            "source": "context_routing" | "command_definitions_e2e" | "command_definitions_smoke" | "directory_scan" | "defaults",
            "doc_paths": ["docs/TESTING.md", ...]
        }
    """
    project = _get_project_for_item(item_id)
    if not project:
        return {
            "project": None,
            "checkout_path": None,
            "surfaces": list(DEFAULT_TEST_DIRS),
            "source": "defaults",
            "doc_paths": [],
        }

    checkout_path = None
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.project_checkout_locations import checkout_for_project

        with db_helpers.connect() as conn:
            checkout = checkout_for_project(conn, project)
            checkout_path = str(checkout) if checkout is not None else None
    except Exception:
        checkout_path = None

    # Strategy 1: context_routing topic 'testing'
    from yoke_core.domain import context_routing as _ctx_routing
    surfaces_from_config: List[str] = []
    doc_paths: List[str] = []
    try:
        doc_paths = _ctx_routing.get_topic_docs(project, "testing")
    except Exception:
        doc_paths = []
    if checkout_path and doc_paths:
        surfaces_from_config = _extract_test_dirs_from_docs(
            checkout_path, doc_paths,
        )

    # Strategy 2: command_definitions (e2e, smoke) path hints.
    # Both scopes may point at playwright-style surfaces — iterate them so
    # each contributes directory hints.
    from yoke_core.domain import command_definitions as _cmd_defs
    _hint_scopes = ("e2e", "smoke")
    command_hint_dirs: List[tuple[str, List[str]]] = []
    for _scope in _hint_scopes:
        cmd_value = _cmd_defs.get_command(project, _scope)
        if not cmd_value:
            continue
        dirs_for_field = _extract_dirs_from_test_command(cmd_value)
        if dirs_for_field:
            command_hint_dirs.append((f"command_definitions_{_scope}", dirs_for_field))

    # Merge: config surfaces + command-hint dirs + fallback scan
    all_surfaces: List[str] = []
    source = "defaults"

    if surfaces_from_config:
        all_surfaces.extend(surfaces_from_config)
        source = "context_routing"

    for field, dirs_for_field in command_hint_dirs:
        for d in dirs_for_field:
            if d not in all_surfaces:
                all_surfaces.append(d)
        if source == "defaults":
            # First command field that contributed surfaces wins the label.
            source = field

    # Strategy 3: deterministic directory scan
    if checkout_path and (not all_surfaces or len(all_surfaces) < 2):
        scanned = _scan_test_directories(checkout_path)
        for d in scanned:
            if d not in all_surfaces:
                all_surfaces.append(d)
        if not surfaces_from_config and not command_hint_dirs and scanned:
            source = "directory_scan"

    # Strategy 4: defaults if nothing found
    if not all_surfaces:
        all_surfaces = list(DEFAULT_TEST_DIRS)
        source = "defaults"

    return {
        "project": project,
        "checkout_path": checkout_path,
        "surfaces": all_surfaces,
        "source": source,
        "doc_paths": doc_paths,
    }


def _extract_test_dirs_from_docs(
    repo_path: str, doc_paths: List[str],
) -> List[str]:
    """Read project testing docs and extract test directory references."""
    dirs: List[str] = []
    # Common patterns that indicate test directories in docs
    dir_patterns = [
        re.compile(r"(?:^|\s)`?([a-zA-Z0-9_./-]+(?:e2e|test|tests|__tests__|spec)[a-zA-Z0-9_./-]*)/`?", re.MULTILINE),
        re.compile(r"(?:^|\s)([a-zA-Z0-9_./-]*(?:e2e|test|tests|__tests__|spec)[a-zA-Z0-9_./-]*)(?:\s|$|:)", re.MULTILINE),
    ]
    for doc_rel in doc_paths:
        doc_full = os.path.join(repo_path, doc_rel)
        if not os.path.isfile(doc_full):
            continue
        try:
            with open(doc_full, "r") as f:
                content = f.read()
        except OSError:
            continue
        for pattern in dir_patterns:
            for m in pattern.finditer(content):
                candidate = m.group(1).strip("`").rstrip("/")
                # Validate: must be a real directory or a path that looks like one
                full = os.path.join(repo_path, candidate)
                if os.path.isdir(full):
                    rel = candidate + "/"
                    if rel not in dirs:
                        dirs.append(rel)
    return dirs


def _extract_dirs_from_test_command(cmd: str) -> List[str]:
    """Extract directory hints from a test command string.

    Example: ``npx playwright test e2e/`` → ``['e2e/']``
    """
    dirs: List[str] = []
    # Look for path-like arguments
    parts = cmd.split()
    for part in parts:
        stripped = part.strip("'\"")
        if not _looks_like_test_surface(stripped):
            continue
        if "/" in stripped or stripped in ("e2e", "tests", "test", "__tests__"):
            # Normalize
            candidate = stripped.rstrip("/") + "/"
            if candidate not in dirs:
                dirs.append(candidate)
    return dirs


def _looks_like_test_surface(value: str) -> bool:
    normalized = value.strip().rstrip("/")
    if not normalized or normalized in {"&&", "||"}:
        return False
    if normalized.startswith("-"):
        return False
    if normalized.startswith(("npm", "npx", "pnpm", "yarn", "python", "python3", "node")):
        return False
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return False
    return any(
        segment in {"e2e", "test", "tests", "__tests__", "spec"}
        or segment.endswith((".spec", ".test"))
        for segment in segments
    )


def _scan_test_directories(repo_path: str) -> List[str]:
    """Scan the repo for common test directories that actually exist."""
    found: List[str] = []
    candidates = DEFAULT_TEST_DIRS + [
        "app/web/e2e/",
        "app/web/__tests__/",
        "src/__tests__/",
        "spec/",
    ]
    for d in candidates:
        full = os.path.join(repo_path, d)
        if os.path.isdir(full):
            if d not in found:
                found.append(d)
    return found
