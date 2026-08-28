"""Render canonical text into marked generated blocks in tracked markdown.

Several canonical contracts have to appear verbatim inside read-raw markdown
surfaces — skill bodies, operator docs, rules files. Each of those surfaces
carries a marker pair::

    <!-- BEGIN GENERATED: <slug> -->
    <!-- END GENERATED: <slug> -->

Everything between the markers is replaced on every run, so the canonical
Python contract stays the only place the text is authored. ``check=True`` is
the same pass without writing: it reports what would change, which is what the
pre-commit gate and the doctor health checks consume.

This module owns the mechanics — marker location, orphan detection, the
inventory walk, and the drift summary. A block family supplies only its slug,
its inventory of repo-relative paths, and a callable returning the content for
one path. :mod:`yoke_core.tools.render_field_note_inline` and
:mod:`yoke_core.tools.render_harness_capability_inline` are the two families.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Callable, Iterable

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


def begin_marker(slug: str) -> str:
    """Return the BEGIN marker literal for a block family."""
    return f"<!-- BEGIN GENERATED: {slug} -->"


def end_marker(slug: str) -> str:
    """Return the END marker literal for a block family."""
    return f"<!-- END GENERATED: {slug} -->"


@dataclasses.dataclass(frozen=True)
class FileRenderOutcome:
    """One inventory file's render result."""

    path: str  # repo-relative
    state: str  # "rendered" | "unchanged" | "missing_markers" | "missing_file"


@dataclasses.dataclass(frozen=True)
class RenderResult:
    """Aggregate render result returned by :func:`render_blocks`."""

    changed: tuple[FileRenderOutcome, ...]
    unchanged: tuple[FileRenderOutcome, ...]
    missing_markers: tuple[FileRenderOutcome, ...]
    missing_files: tuple[FileRenderOutcome, ...]
    orphan_marker_errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        # Orphan markers (BEGIN without END, multiple pairs in one file) are
        # the only hard-fail class. An inventory file lacking a marker pair
        # entirely is advisory: a family may enumerate a surface before the
        # marker is inserted into it.
        return not self.orphan_marker_errors


def rewrite_between_markers(
    original: str, replacement: str, *, slug: str,
) -> str | None:
    """Return rewritten content; None when markers are missing or ill-formed."""
    begin, end = begin_marker(slug), end_marker(slug)
    begin_idx = original.find(begin)
    end_idx = original.find(end)
    if begin_idx < 0 or end_idx < 0:
        return None
    if end_idx < begin_idx:
        return None
    next_begin = original.find(begin, begin_idx + len(begin))
    if 0 <= next_begin < end_idx:
        return None
    head = original[: begin_idx + len(begin)]
    tail = original[end_idx:]
    return f"{head}\n{replacement}{tail}"


def scan_for_orphans(text: str, *, slug: str) -> str | None:
    """Return a description of the orphan condition, or None if clean."""
    begin, end = begin_marker(slug), end_marker(slug)
    has_begin = begin in text
    has_end = end in text
    if has_begin and not has_end:
        return "BEGIN marker without matching END"
    if has_end and not has_begin:
        return "END marker without matching BEGIN"
    if text.count(begin) > 1 or text.count(end) > 1:
        return "multiple marker pairs in one file (not supported)"
    return None


def render_blocks(
    target_root: pathlib.Path,
    *,
    slug: str,
    inventory: Iterable[str],
    content_for_path: Callable[[str], str],
    check: bool = False,
) -> RenderResult:
    """Render *slug*'s canonical block into every inventory file."""
    changed: list[FileRenderOutcome] = []
    unchanged: list[FileRenderOutcome] = []
    missing_markers: list[FileRenderOutcome] = []
    missing_files: list[FileRenderOutcome] = []
    orphan_errors: list[str] = []

    for rel_path in inventory:
        abs_path = target_root / rel_path
        if not abs_path.exists():
            missing_files.append(
                FileRenderOutcome(path=rel_path, state="missing_file")
            )
            continue

        original = abs_path.read_text(encoding="utf-8")

        orphan = scan_for_orphans(original, slug=slug)
        if orphan is not None:
            orphan_errors.append(f"{rel_path}: {orphan}")
            missing_markers.append(
                FileRenderOutcome(path=rel_path, state="missing_markers")
            )
            continue

        rewritten = rewrite_between_markers(
            original, content_for_path(rel_path), slug=slug,
        )
        if rewritten is None:
            missing_markers.append(
                FileRenderOutcome(path=rel_path, state="missing_markers")
            )
            continue

        if rewritten == original:
            unchanged.append(
                FileRenderOutcome(path=rel_path, state="unchanged")
            )
            continue

        changed.append(FileRenderOutcome(path=rel_path, state="rendered"))
        if not check:
            assert_target_under_session_work_authority(abs_path)
            abs_path.write_text(rewritten, encoding="utf-8")

    return RenderResult(
        changed=tuple(changed),
        unchanged=tuple(unchanged),
        missing_markers=tuple(missing_markers),
        missing_files=tuple(missing_files),
        orphan_marker_errors=tuple(orphan_errors),
    )


def format_drift_summary(
    result: RenderResult,
    *,
    check: bool,
    family_label: str,
    repair_command: str,
) -> str:
    """Render the operator-facing drift report for one family's result."""
    parts: list[str] = []
    if check and result.changed:
        parts.append(
            f"ERROR: {family_label} renderer would change "
            f"{len(result.changed)} file(s):"
        )
        for outcome in result.changed:
            parts.append(f"  - {outcome.path}")
        parts.append("")
        parts.append(f"Run `{repair_command}` and re-stage.")
    if result.missing_markers and check:
        # Advisory only: a family may enumerate a surface in one change and
        # insert its marker pair in the next.
        parts.append(
            f"NOTE: {len(result.missing_markers)} inventory file(s) lack a "
            f"valid marker pair (advisory):"
        )
        for outcome in result.missing_markers:
            parts.append(f"  - {outcome.path}")
    if result.orphan_marker_errors:
        parts.append("Orphan-marker details:")
        for line in result.orphan_marker_errors:
            parts.append(f"  - {line}")
    if result.missing_files:
        parts.append(
            f"WARNING: {len(result.missing_files)} inventory file(s) missing "
            f"on disk (skipped):"
        )
        for outcome in result.missing_files:
            parts.append(f"  - {outcome.path}")
    return "\n".join(parts) + ("\n" if parts else "")


__all__ = (
    "FileRenderOutcome",
    "RenderResult",
    "begin_marker",
    "end_marker",
    "format_drift_summary",
    "render_blocks",
    "rewrite_between_markers",
    "scan_for_orphans",
)
