"""Parsers for Codex ``apply_patch`` payload bodies.

Two coexisting public surfaces serve different consumers within Yoke's
hook substrate. Both parse the V4A patch grammar permissively (never
raise on malformed input) and return whatever directive lines they
recognize so hot-path hooks degrade gracefully on bad envelopes
(per OQ-2 in the lane H spec).

Hot-path hook consumers (path-claim guards, harness policy pipeline) use:

- :class:`PatchPaths` — dataclass with ``added``, ``updated``, ``moved``,
  ``deleted`` lists of paths plus an :func:`PatchPaths.all_paths` helper.
- :func:`parse_patch` — returns :class:`PatchPaths`. Move destinations
  land in ``moved`` (sourced from ``*** Move to:`` follow-up directives).

Telemetry / observe consumers (Codex hook payload normalization) use:

- :class:`ApplyPatchSummary` — added/updated/deleted lists, ``moved``
  as ``List[Tuple[str, str]]`` of (src, dst), plus ``well_formed`` flag
  tracking whether ``*** Begin Patch`` / ``*** End Patch`` markers were
  present, and a :func:`ApplyPatchSummary.changed_paths` property that
  flattens every bucket (including both move endpoints) for path-claim
  coverage checks.
- :func:`parse_patch_body` — returns :class:`ApplyPatchSummary`.

Envelope shape (Codex ``apply_patch`` tool):

::

    *** Begin Patch
    *** Add File: path/to/file
    +contents
    *** Update File: path/to/file
    @@
     unchanged
    -old
    +new
    *** Delete File: path/to/file
    *** Move File: path/from -> path/to
    *** Update File: path/from
    *** Move to: path/to
    @@
    ...
    *** End Patch

Both forms of move directive are accepted — the inline ``*** Move File:
src -> dst`` and the ``*** Move to:`` follow-up after a bare ``*** Update
File:`` header. A single envelope may contain multiple file directives
back to back.

Tolerance rules shared by both parsers:

- Missing ``*** Begin Patch`` / ``*** End Patch`` markers do not abort —
  any directive lines we recognise are still extracted.
- Unknown directive lines are skipped silently.
- Empty / non-string input returns an empty result.
- Whitespace around path strings is stripped.
- Duplicate paths within the same bucket are de-duplicated while
  preserving first-seen order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Tuple


# ---------------------------------------------------------------------------
# Hot-path API (PatchPaths / parse_patch) — used by harness policy pipeline
# ---------------------------------------------------------------------------


@dataclass
class PatchPaths:
    """Per-bucket changed-path lists from a parsed ``apply_patch`` body."""

    added: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    moved: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)

    def all_paths(self) -> List[str]:
        """Return the union of every bucket, de-duplicated, first-seen order."""
        return _dedup(
            list(self.added)
            + list(self.updated)
            + list(self.moved)
            + list(self.deleted)
        )


_ADD_PREFIX = "*** Add File:"
_UPDATE_PREFIX = "*** Update File:"
_DELETE_PREFIX = "*** Delete File:"
_MOVE_PREFIX = "*** Move to:"


def parse_patch(body: str) -> PatchPaths:
    """Parse a Codex ``apply_patch`` envelope body into a :class:`PatchPaths`.

    Always returns a :class:`PatchPaths`; never raises. Malformed input
    produces empty buckets — callers (hooks) must never fail-closed on a
    bad envelope.
    """
    result = PatchPaths()
    if not isinstance(body, str) or not body:
        return result

    try:
        lines = body.splitlines()
    except Exception:
        return result

    current_update: str | None = None

    for raw_line in lines:
        line = raw_line.lstrip()
        if not line.startswith("***"):
            continue

        path = _extract_path(line, _ADD_PREFIX)
        if path is not None:
            current_update = None
            _append_unique(result.added, path)
            continue

        path = _extract_path(line, _UPDATE_PREFIX)
        if path is not None:
            current_update = path
            _append_unique(result.updated, path)
            continue

        path = _extract_path(line, _DELETE_PREFIX)
        if path is not None:
            current_update = None
            _append_unique(result.deleted, path)
            continue

        path = _extract_path(line, _MOVE_PREFIX)
        if path is not None:
            _append_unique(result.moved, path)
            current_update = None
            continue

        continue

    return result


def _extract_path(line: str, prefix: str) -> str | None:
    if not line.startswith(prefix):
        return None
    remainder = line[len(prefix):].strip()
    if not remainder:
        return None
    return remainder


def _append_unique(bucket: List[str], path: str) -> None:
    if path not in bucket:
        bucket.append(path)


def _dedup(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# Telemetry API (ApplyPatchSummary / parse_patch_body) — used by Codex hook
# payload normalization to surface changed paths into the events ledger.
# ---------------------------------------------------------------------------


_BEGIN_PATCH_RE = re.compile(r"^\*\*\*\s*Begin Patch\s*$")
_END_PATCH_RE = re.compile(r"^\*\*\*\s*End Patch\s*$")
_ADD_RE = re.compile(r"^\*\*\*\s*Add File:\s*(.+?)\s*$")
_UPDATE_RE = re.compile(r"^\*\*\*\s*Update File:\s*(.+?)\s*$")
_DELETE_RE = re.compile(r"^\*\*\*\s*Delete File:\s*(.+?)\s*$")
_MOVE_INLINE_RE = re.compile(r"^\*\*\*\s*Move File:\s*(.+?)\s*->\s*(.+?)\s*$")
_MOVE_TO_RE = re.compile(r"^\*\*\*\s*Move to:\s*(.+?)\s*$")


@dataclass
class ApplyPatchSummary:
    """Result of parsing an ``apply_patch`` patch body."""

    added: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    moved: List[Tuple[str, str]] = field(default_factory=list)
    well_formed: bool = False

    @property
    def changed_paths(self) -> List[str]:
        """Flat list of paths the patch would touch.

        For moves, both source and destination are included so path-claim
        coverage checks see the complete set. Order is added → updated →
        deleted → moved (source then dest), de-duplicated while preserving
        first-seen position.
        """
        ordered: List[str] = []
        seen: set[str] = set()
        for path in self.added + self.updated + self.deleted:
            if path and path not in seen:
                ordered.append(path)
                seen.add(path)
        for src, dst in self.moved:
            for path in (src, dst):
                if path and path not in seen:
                    ordered.append(path)
                    seen.add(path)
        return ordered


def parse_patch_body(body: str) -> ApplyPatchSummary:
    """Parse an ``apply_patch`` body string.

    Returns an :class:`ApplyPatchSummary` whose ``well_formed`` is ``True``
    when both a ``*** Begin Patch`` and a ``*** End Patch`` envelope marker
    were found. Missing markers do not raise — the parser still extracts
    whatever directive lines it recognizes so partial/malformed payloads
    surface as best-effort summaries rather than empty silence.
    """
    summary = ApplyPatchSummary()
    if not isinstance(body, str) or not body:
        return summary

    saw_begin = False
    saw_end = False
    pending_move_src: str | None = None
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line:
            pending_move_src = None
            continue

        if _BEGIN_PATCH_RE.match(line):
            saw_begin = True
            pending_move_src = None
            continue
        if _END_PATCH_RE.match(line):
            saw_end = True
            pending_move_src = None
            continue

        m = _MOVE_INLINE_RE.match(line)
        if m:
            summary.moved.append((m.group(1), m.group(2)))
            pending_move_src = None
            continue

        m = _ADD_RE.match(line)
        if m:
            summary.added.append(m.group(1))
            pending_move_src = None
            continue

        m = _UPDATE_RE.match(line)
        if m:
            summary.updated.append(m.group(1))
            pending_move_src = m.group(1)
            continue

        m = _DELETE_RE.match(line)
        if m:
            summary.deleted.append(m.group(1))
            pending_move_src = None
            continue

        m = _MOVE_TO_RE.match(line)
        if m and pending_move_src is not None:
            try:
                summary.updated.remove(pending_move_src)
            except ValueError:
                pass
            summary.moved.append((pending_move_src, m.group(1)))
            pending_move_src = None
            continue

    summary.well_formed = saw_begin and saw_end
    return summary
