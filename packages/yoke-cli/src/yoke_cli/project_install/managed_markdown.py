"""Marker-delimited Yoke-managed blocks inside co-owned Markdown files.

External projects may already own their ``AGENTS.md`` / ``CLAUDE.md`` /
``CODEX.md``, so the installer owns exactly one marker-delimited block inside
each file and never touches content outside the markers:

* file absent             -> create it with just our block
* file present, no block  -> insert our block at the top, keep the rest below
* file present, has block -> overwrite the block, keep everything around it

The markers announce "do not edit inside"; refresh always rewrites the block to
current, and uninstall strips exactly the block (deleting an installer-created
file only when nothing else remains). Block *content* is rendered server-side
and carried in the bundle's ``managed_markdown`` key; this module owns only the
placement/preservation mechanics and the manifest records that keep refresh and
uninstall clean. Distinct from :mod:`files` (whole-file writes) and
:mod:`hooks` (JSON subtree merge).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_cli.project_install.files import (
    HOOK_MERGE_TARGETS,
    ProjectInstallError,
    assert_resolved_targets_within,
    remove_empty_parents,
    sha256_text,
)

from yoke_contracts.project_contract.managed_block import (
    MANAGED_BLOCK_BEGIN,
    MANAGED_BLOCK_END,
    block_span as _block_span,
    render_block,
)


def assert_safe_managed_markdown_paths(paths) -> None:
    """Refuse managed-markdown targets that could escape or collide.

    Managed blocks live in repo-root-relative Markdown files. They must never
    traverse ``..``, live under ``.yoke/`` (contract territory), or name a hook
    settings file (that content flows through the bundle's ``hooks`` subtree).
    """
    for raw in paths:
        path = Path(raw)
        bad = (
            not raw
            or path.is_absolute()
            or ".." in path.parts
            or raw in HOOK_MERGE_TARGETS
            or path.parts[0] == ".yoke"
            or not raw.endswith(".md")
        )
        if bad:
            raise ProjectInstallError(
                f"bundle names an unsafe managed-markdown path {raw!r}: managed "
                "blocks must be repo-relative '.md' files outside .yoke/ and must "
                "not name hook settings files"
            )


def plan_markdown_block(current: Optional[str], block: str) -> Tuple[str, str]:
    """Pure planner: return (action, new_text) for one managed file.

    ``current`` is the file's existing text, or ``None`` when the file is
    absent. ``action`` is one of ``created`` / ``inserted`` / ``refreshed`` /
    ``unchanged``. Content outside the markers is always preserved verbatim.
    """
    rendered = render_block(block)
    if current is None:
        return "created", rendered + "\n"
    span = _block_span(current)
    if span is None:
        if current.strip():
            new = rendered + "\n\n" + current.lstrip("\n")
        else:
            new = rendered + "\n"
        return "inserted", new
    start, end = span
    before, after = current[:start], current[end:]
    new = before + rendered + after
    if new == current:
        return "unchanged", current
    return "refreshed", new


def plan_markdown_removal(
    current: str, *, file_created: bool
) -> Tuple[str, Optional[str]]:
    """Pure planner for uninstall: return (action, new_text_or_None).

    ``None`` new text means delete the file (installer created it and nothing
    but the block remained). Otherwise the block is stripped and surrounding
    project content is preserved.
    """
    span = _block_span(current)
    if span is None:
        return "absent", current
    start, end = span
    before, after = current[:start], current[end:]
    remainder = before + after
    if file_created and not remainder.strip():
        return "removed_file", None
    stitched = before.rstrip("\n")
    tail = after.lstrip("\n")
    if stitched and tail:
        new = stitched + "\n\n" + tail
    else:
        new = (stitched or tail).rstrip("\n")
    new = new + "\n" if new else ""
    return "removed_block", new


def _action_line(action: str, rel: str) -> str:
    """Clear, user-facing report line for one managed-markdown outcome."""
    return {
        "created": f"Created: {rel} (Yoke rules block)",
        "inserted": (
            f"Updated: {rel} (inserted Yoke rules block at top; "
            "your existing content preserved)"
        ),
        "refreshed": (
            f"Updated: {rel} (refreshed Yoke rules block; "
            "your content outside it preserved)"
        ),
        "unchanged": f"Exists: {rel} (Yoke rules block up to date)",
    }[action]


def _preview_line(action: str, rel: str) -> str:
    """Future-tense report line for the refresh/review preview."""
    return {
        "created": f"Would create: {rel} (Yoke rules block)",
        "inserted": (
            f"Would update: {rel} (insert Yoke rules block at top; "
            "your existing content preserved)"
        ),
        "refreshed": (
            f"Would update: {rel} (refresh Yoke rules block; "
            "your content outside it preserved)"
        ),
        "unchanged": f"Would keep: {rel} (Yoke rules block up to date)",
    }[action]


def resolve_targets(managed_markdown: Dict[str, Any]) -> List[Dict[str, str]]:
    """Resolve the bundle's {blocks, targets} into [{path, content}] entries."""
    blocks = managed_markdown.get("blocks")
    targets = managed_markdown.get("targets")
    if not isinstance(blocks, dict) or not isinstance(targets, list):
        raise ProjectInstallError(
            "bundle managed_markdown must carry object 'blocks' and array "
            "'targets'"
        )
    resolved: List[Dict[str, str]] = []
    for target in targets:
        if not isinstance(target, dict):
            raise ProjectInstallError("managed_markdown targets must be objects")
        rel = target.get("path")
        name = target.get("block")
        if not isinstance(rel, str) or not rel:
            raise ProjectInstallError("managed_markdown target missing 'path'")
        if not isinstance(name, str) or name not in blocks:
            raise ProjectInstallError(
                f"managed_markdown target {rel!r} names unknown block {name!r}"
            )
        content = blocks[name]
        if not isinstance(content, str) or not content.strip():
            raise ProjectInstallError(
                f"managed_markdown block {name!r} is empty"
            )
        resolved.append({"path": rel, "content": content})
    assert_safe_managed_markdown_paths(entry["path"] for entry in resolved)
    return resolved


def _read_current(target: Path) -> Optional[str]:
    if not target.exists():
        return None
    try:
        return target.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectInstallError(
            f"{target} exists but is not readable UTF-8 text ({exc}); move it "
            "aside and rerun `yoke project install`"
        ) from exc


def apply_managed_markdown(
    repo_root: Path,
    managed_markdown: Optional[Dict[str, Any]],
    old_records: Optional[Dict[str, Dict[str, Any]]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Apply every managed-markdown block; return (records, report).

    ``records`` maps each managed path to ``{"file_created": bool,
    "block_sha": str}`` for clean refresh/uninstall. ``report`` carries
    ``actions`` (user-facing lines), ``written`` (paths mutated), and counts.
    """
    prior = dict(old_records or {})
    records: Dict[str, Dict[str, Any]] = {}
    actions: List[str] = []
    written: List[str] = []
    if not managed_markdown:
        return records, {"actions": actions, "written": written, "changed": 0}
    entries = resolve_targets(managed_markdown)
    assert_resolved_targets_within(
        repo_root,
        [entry["path"] for entry in entries],
        context="managed markdown mutation",
    )
    for entry in entries:
        rel, block = entry["path"], entry["content"]
        target = repo_root / rel
        current = _read_current(target)
        action, new_text = plan_markdown_block(current, block)
        created = current is None or bool(prior.get(rel, {}).get("file_created"))
        records[rel] = {
            "file_created": created,
            "block_sha": sha256_text(render_block(block)),
        }
        actions.append(_action_line(action, rel))
        if action == "unchanged":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_text, encoding="utf-8")
        written.append(rel)
    return records, {
        "actions": actions,
        "written": written,
        "changed": len(written),
    }


def preview_managed_markdown(
    repo_root: Path,
    managed_markdown: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Plan managed-markdown mutations without writing (review/preview).

    The action for each file depends only on the file's current on-disk shape
    (absent / no block / has block), so no prior manifest records are needed.
    """
    actions: List[str] = []
    would_write: List[str] = []
    if not managed_markdown:
        return {"actions": actions, "would_write": would_write}
    entries = resolve_targets(managed_markdown)
    assert_resolved_targets_within(
        repo_root,
        [entry["path"] for entry in entries],
        context="managed markdown mutation",
    )
    for entry in entries:
        current = _read_current(repo_root / entry["path"])
        action, _new = plan_markdown_block(current, entry["content"])
        actions.append(_preview_line(action, entry["path"]))
        if action != "unchanged":
            would_write.append(entry["path"])
    return {"actions": actions, "would_write": would_write}


def remove_managed_markdown(
    repo_root: Path,
    records: Optional[Dict[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    """Uninstall pass: strip each managed block; delete installer-created,
    now-empty files. Never touches a file we have no record for."""
    removed_files: List[str] = []
    stripped_blocks: List[str] = []
    warnings: List[str] = []
    if not records:
        return {
            "removed_files": removed_files,
            "stripped_blocks": stripped_blocks,
            "warnings": warnings,
        }
    assert_resolved_targets_within(
        repo_root, list(records), context="managed markdown removal",
    )
    for rel, record in sorted(records.items()):
        target = repo_root / rel
        if not target.is_file():
            continue
        current = _read_current(target)
        if current is None:
            continue
        file_created = bool(record.get("file_created"))
        action, new_text = plan_markdown_removal(
            current, file_created=file_created
        )
        if action == "absent":
            continue
        if action == "removed_file":
            target.unlink()
            remove_empty_parents(repo_root, rel)
            removed_files.append(rel)
        else:
            target.write_text(new_text or "", encoding="utf-8")
            stripped_blocks.append(rel)
    return {
        "removed_files": removed_files,
        "stripped_blocks": stripped_blocks,
        "warnings": warnings,
    }


__all__ = [
    "MANAGED_BLOCK_BEGIN",
    "MANAGED_BLOCK_END",
    "apply_managed_markdown",
    "assert_safe_managed_markdown_paths",
    "plan_markdown_block",
    "plan_markdown_removal",
    "preview_managed_markdown",
    "remove_managed_markdown",
    "render_block",
    "resolve_targets",
]
