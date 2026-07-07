"""Template discovery + bundle rendering — server side of ``yoke templates``.

``GET /v1/templates`` serves :func:`list_templates` and
``GET /v1/templates/{name}`` serves :func:`build_template_bundle`: the raw
template material under ``templates/<name>/**`` in the server's own code
tree, delivered with ``{{placeholders}}`` intact so a no-checkout project
repo can pull ops/infra raw material without local access to a Yoke
source checkout (Template registry contract / template registry delivery). Rendering and placeholder
substitution stay with the server-side ``project_renderer``; this surface
ships files verbatim.

Sibling of :mod:`yoke_core.domain.install_bundle` (same determinism
contract): files are sorted by bundle path, no timestamps are embedded,
and binary / non-UTF-8 files are skipped — here additionally counted so
clients can report the omission. No DB access — templates are server-tree
content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.template_bundle import (
    TEMPLATE_BUNDLE_SCHEMA,
    TEMPLATE_PRODUCT_BOUNDARY_FIELD,
    TEMPLATE_PRODUCT_BOUNDARY_PRODUCT,
    TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN,
)
from yoke_core.domain.install_bundle import server_tree_root, yoke_version

# Server-tree source dir (relative to the tree root).
TEMPLATES_SOURCE = "templates"

# Optional per-template metadata file carrying description and boundary metadata.
TEMPLATE_META_FILENAME = "template.json"


class TemplateBundleError(RuntimeError):
    """The template surface cannot be rendered; message names the repair."""


class TemplateNotFoundError(TemplateBundleError):
    """The requested name has no ``templates/<name>/`` directory."""


class TemplateAccessDeniedError(TemplateBundleError):
    """The requested template requires an explicit source-dev/admin opt-in."""


def _templates_root() -> Path:
    root = server_tree_root() / TEMPLATES_SOURCE
    if not root.is_dir():
        raise TemplateBundleError(
            f"templates source dir is missing from the server tree: {root}"
        )
    return root


def _read_text(path: Path) -> Optional[str]:
    """Return the file's UTF-8 text, or ``None`` for non-text/binary files."""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _metadata(template_dir: Path) -> Dict[str, Any]:
    """The template.json object, or ``{}`` when absent/unreadable."""
    raw = _read_text(template_dir / TEMPLATE_META_FILENAME)
    if raw is None:
        return {}
    try:
        meta = json.loads(raw)
    except ValueError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _description(template_dir: Path) -> str:
    """The template.json ``description``, or ``""`` when absent/unreadable."""
    description = _metadata(template_dir).get("description")
    return str(description) if description else ""


def _product_boundary(template_dir: Path) -> str:
    meta = _metadata(template_dir)
    boundary = meta.get(TEMPLATE_PRODUCT_BOUNDARY_FIELD)
    if not boundary:
        return TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
    value = str(boundary)
    if value in (
        TEMPLATE_PRODUCT_BOUNDARY_PRODUCT,
        TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN,
    ):
        return value
    raise TemplateBundleError(
        f"{template_dir / TEMPLATE_META_FILENAME} has unsupported "
        f"{TEMPLATE_PRODUCT_BOUNDARY_FIELD} {value!r}"
    )


def _collect_files(template_dir: Path) -> Tuple[List[Dict[str, str]], int]:
    """Every text file under ``template_dir`` plus the binary-skip count."""
    files: List[Dict[str, str]] = []
    skipped = 0
    for path in sorted(p for p in template_dir.rglob("*") if p.is_file()):
        content = _read_text(path)
        if content is None:
            skipped += 1  # binary / non-UTF-8 — never shipped, but counted
            continue
        rel = path.relative_to(template_dir).as_posix()
        files.append({"path": rel, "content": content})
    files.sort(key=lambda entry: entry["path"])
    return files, skipped


def list_templates() -> List[Dict[str, Any]]:
    """Every template directory with name, description, and text-file count.

    ``file_count`` counts the deliverable text files — the same set
    :func:`build_template_bundle` ships — so list and fetch agree.
    """
    listing: List[Dict[str, Any]] = []
    for template_dir in sorted(
        p for p in _templates_root().iterdir() if p.is_dir()
    ):
        files, _skipped = _collect_files(template_dir)
        listing.append({
            "name": template_dir.name,
            "description": _description(template_dir),
            TEMPLATE_PRODUCT_BOUNDARY_FIELD: _product_boundary(template_dir),
            "file_count": len(files),
        })
    return listing


def build_template_bundle(
    name: str,
    *,
    include_source_dev_admin: bool = False,
) -> Dict[str, Any]:
    """Render the deterministic raw-file bundle for template ``name``.

    Raises :class:`TemplateNotFoundError` for an unknown (or non-plain)
    name, :class:`TemplateAccessDeniedError` when source-dev/admin material
    lacks an explicit opt-in, and :class:`TemplateBundleError` when the
    server tree lacks the templates source dir.
    """
    root = _templates_root()
    safe = str(name).strip()
    if not safe or safe in (".", "..") or Path(safe).name != safe:
        raise TemplateNotFoundError(
            f"template name {name!r} is not a plain directory name"
        )
    target = root / safe
    if not target.is_dir():
        known = ", ".join(sorted(p.name for p in root.iterdir() if p.is_dir()))
        raise TemplateNotFoundError(
            f"template {safe!r} does not exist on this env; "
            f"known templates: {known}"
        )
    boundary = _product_boundary(target)
    if (
        boundary == TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN
        and not include_source_dev_admin
    ):
        raise TemplateAccessDeniedError(
            f"template {safe!r} is source-dev/admin material; rerun with "
            "`yoke templates fetch --source-dev-admin` only from an "
            "operator-approved source-dev/admin flow"
        )
    files, binaries_skipped = _collect_files(target)
    return {
        "bundle_schema": TEMPLATE_BUNDLE_SCHEMA,
        "yoke_version": yoke_version(),
        "template": safe,
        "description": _description(target),
        TEMPLATE_PRODUCT_BOUNDARY_FIELD: boundary,
        "files": files,
        "binary_files_skipped": binaries_skipped,
    }


__all__ = [
    "TEMPLATE_BUNDLE_SCHEMA",
    "TEMPLATES_SOURCE",
    "TEMPLATE_META_FILENAME",
    "TemplateBundleError",
    "TemplateAccessDeniedError",
    "TemplateNotFoundError",
    "build_template_bundle",
    "list_templates",
]
