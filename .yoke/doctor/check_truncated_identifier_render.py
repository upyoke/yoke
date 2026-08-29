"""HC-truncated-identifier-render: no surface shows part of an identifier.

A session id is not a git commit. Short SHAs work because a hash spreads
uniformly, so a prefix is a near-unique handle. Session ids do not: some
are readable strings whose leading characters are a constant, and the
UUID-shaped ones are time-ordered, so sessions started in the same window
share leading hex by construction. Measured on one live control plane,
5,249 sessions produced 4,847 distinct eight-character prefixes — 402
collisions already, with 36 sessions behind a single prefix.

That makes a rendered fragment worse than useless. A reader who copies
one out of a watcher line, a board cell, or a card is not merely unable
to address the session; they can address a *different* one and never be
told. So no surface renders part of one, and this check keeps the sweep
from regressing.

Three shapes are flagged:

- slicing an identifier-named expression in Python;
- an identifier column in a CLI table that declares a width, since the
  table renderer truncates any cell wider than its column;
- slicing an identifier-named expression in browser code.

Digests are deliberately out of scope: a content hash or commit sha
shown as a fingerprint is the case the uniform-distribution argument
actually covers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)
from yoke_core.engines.doctor_tree_scan import iter_tree_files
from yoke_project_checks._declare import self_project_checks

HC_SLUG = "truncated-identifier-render"
HC_NAME = "No surface renders part of an identifier"
HC_ID = f"HC-{HC_SLUG}"

#: Trees whose rendering this project owns. Separately versioned Pack
#: source and the generated install-bundle snapshot are not authored here.
_SCAN_ROOTS = ("packages", "runtime", ".yoke")
_SKIP_PREFIXES = (
    "docs/archive/",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/",
)
#: A test asserting this guard has to be able to write the shape it
#: forbids, and no test file is a surface anyone reads an id from.
_TEST_FILE_PREFIX = "test_"
_TEST_FILE_SUFFIX = "_test.py"
_PRUNE_DIRS = frozenset({"__pycache__", "node_modules", "build", "dist"})

#: Names holding a long opaque identifier — the values a reader copies in
#: order to address something. Integer keys (``project_id``, ``item_id``,
#: ``actor_id``) are deliberately absent: they are neither elided by a
#: column width nor ambiguous when they are. Matching is by suffix, so
#: every qualified form (``target_session_id``, ``sender_session_id``,
#: ``registered_session_id``) is covered without being listed.
_IDENTIFIER_SUFFIXES = (
    "session_id",
    "sessionId",
    "message_id",
    "messageId",
    "attempt_id",
    "attemptId",
    "launch_id",
    "launchId",
    "relay_id",
    "relayId",
    "machine_id",
    "machineId",
    "request_id",
    "requestId",
    "thread_id",
    "threadId",
    "identifier",
    "sid",
)
#: A whole name ending in one of those, and not a plural naming a list:
#: capping ``session_ids`` is a row limit, not a truncated value.
_NAME_TAIL = "(?:" + "|".join(_IDENTIFIER_SUFFIXES) + r")(?![\w$])"
_IDENTIFIER_NAME = rf"[A-Za-z_$][\w$.]*{_NAME_TAIL}|{_NAME_TAIL}"

#: A leading slice of an identifier-named expression in Python, taken
#: directly or through a wrapping call.
_PY_SLICE = re.compile(
    rf"(?:{_IDENTIFIER_NAME}|\([^()]*(?:{_IDENTIFIER_NAME})[^()]*\))\s*\[\s*:"
)
#: A table column reading an identifier while declaring a width. The
#: renderer elides any cell wider than its column, so the width is the
#: truncation even though no slice appears.
_PY_COLUMN = re.compile(
    rf'^\s*\(\s*"[^"]+"\s*,\s*lambda\b.*(?:{_IDENTIFIER_NAME}).*,'
    r"\s*\d+\s*\),?\s*$"
)
#: A leading slice of an identifier-named expression in browser code,
#: taken directly or through a wrapping call.
_JS_SLICE = re.compile(
    rf"(?:{_IDENTIFIER_NAME}|\([^()]*(?:{_IDENTIFIER_NAME})[^()]*\))\s*"
    r"\.(?:slice|substring|substr)\(\s*0\s*,"
)

#: Reads of an identifier an external tool composed, where the fragment is
#: that tool's own naming and not something Yoke renders for a reader.
_EXEMPTIONS: Tuple[Tuple[str, str], ...] = (
    (
        "packages/yoke-harness/src/yoke_harness/hooks/identity_claude_presentation.py",
        "Claude names its own job-state directory by the leading characters "
        "of its session id; this reads that path rather than showing an id.",
    ),
)


@dataclass(frozen=True)
class TruncationHit:
    """One rendered fragment, located for the reader who must fix it."""

    relative_path: str
    line: int
    snippet: str

    def __str__(self) -> str:
        return f"{self.relative_path}:{self.line}: {self.snippet}"


def _hits_in_text(relative_path: str, text: str) -> Iterator[TruncationHit]:
    patterns = (
        (_PY_SLICE, _PY_COLUMN)
        if relative_path.endswith(".py")
        else (_JS_SLICE,)
    )
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if any(pattern.search(line) for pattern in patterns):
            yield TruncationHit(relative_path, number, stripped[:160])


def _is_scannable(relative_path: str) -> bool:
    if any(relative_path.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return False
    name = relative_path.rsplit("/", 1)[-1]
    if name.startswith(_TEST_FILE_PREFIX) or name.endswith(_TEST_FILE_SUFFIX):
        return False
    return not any(relative_path == exempt for exempt, _why in _EXEMPTIONS)


def _iter_sources(repo_root: Path) -> Iterable[Path]:
    for root_name in _SCAN_ROOTS:
        base = repo_root / root_name
        if not base.is_dir():
            continue
        for suffix in ("*.py", "*.js"):
            yield from iter_tree_files(base, suffix, prune_dir_names=_PRUNE_DIRS)


def scan(repo_root: Path) -> List[TruncationHit]:
    """Return every rendered identifier fragment in the authored tree."""
    hits: List[TruncationHit] = []
    for path in _iter_sources(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        if not _is_scannable(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits.extend(_hits_in_text(relative, text))
    return hits


def stale_exemptions(repo_root: Path) -> List[str]:
    """Return exempted paths that no longer truncate anything."""
    stale: List[str] = []
    for relative, _why in _EXEMPTIONS:
        path = repo_root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            stale.append(f"{relative} (unreadable)")
            continue
        if not list(_hits_in_text(relative, text)):
            stale.append(relative)
    return stale


def hc_truncated_identifier_render(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-truncated-identifier-render: identifiers are shown whole."""
    del conn, args
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(HC_ID, HC_NAME, "PASS", "No repo root resolved — skipping.")
        return
    repo_root = Path(repo_root_str)
    hits = scan(repo_root)
    stale = stale_exemptions(repo_root)
    if not hits and not stale:
        rec.record(HC_ID, HC_NAME, "PASS", "")
        return
    detail = [
        "A rendered identifier fragment names a set of sessions, not one "
        "session, and a reader who copies it can address the wrong worker. "
        "Show the whole id, or a label that cannot be mistaken for one:",
    ]
    detail.extend(f"  - {hit}" for hit in hits[:40])
    if len(hits) > 40:
        detail.append(f"  ... and {len(hits) - 40} more")
    if stale:
        detail.append(
            "Exempted paths that no longer truncate — drop the exemption "
            "from _EXEMPTIONS: " + ", ".join(stale)
        )
    rec.record(HC_ID, HC_NAME, "FAIL", "\n".join(detail))


PROJECT_HEALTH_CHECKS = self_project_checks(
    (HC_SLUG, HC_NAME, hc_truncated_identifier_render),
)

__all__ = [
    "HC_ID",
    "HC_NAME",
    "HC_SLUG",
    "PROJECT_HEALTH_CHECKS",
    "TruncationHit",
    "hc_truncated_identifier_render",
    "scan",
    "stale_exemptions",
]
