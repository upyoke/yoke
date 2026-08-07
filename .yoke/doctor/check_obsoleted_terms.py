"""HC-obsoleted-terms: flag retired surface names that have leaked into live files.

Background
----------
When a column, table, module, CLI command, helper, or file is retired, its name
must not linger in tracked content. A stale reference teaches future agents (and
humans) a surface that no longer works, and the fix for the resulting confusion
is another wasted turn. The Obsoleted Terms Hard Rule in ``AGENTS.md`` formalises
this; ``HC-obsoleted-terms`` is the check that enforces it.

Maintenance
-----------
Every retirement of a surface must add one entry to ``OBSOLETED_TERM_PATTERNS``
in the *same commit* that removes or supersedes the surface. Patterns are stored
as regex fragments with escaped separators for symbol-form names; this keeps the
residue checks that operators run from the shell from matching the pattern
declaration in this file, while still compiling to a regex that matches the
bare retired surface in scanned files. Add a short human-readable label in
:data:`OBSOLETED_TERM_LABELS` so the doctor report names the term clearly.

Posture
-------
The check ships at ``severity=warn`` for the first release, matching the posture
of ``HC-historical-yok-n-cruft``. Doctor exits nonzero only on FAILs; warnings
surface in the report so owners can sweep prose on their schedule without
blocking unrelated work.

Scope policy: ``docs/archive/**`` and structured backlog fields on items in
terminal statuses are excluded as intentional historical provenance, per
``docs/archive/decisions/historical-obsoleted-hook-refs.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.engines.doctor_hc_obsoleted_terms_allowlists import (
    EXEMPT_PATH_SEGMENTS,
    PATH_ALLOWLIST_ALL_PATTERNS,
)
from yoke_core.engines.doctor_hc_obsoleted_terms_backlog import scan_backlog_fields
from yoke_core.engines.doctor_obsoleted_scan_scope import (
    SCAN_DIRS_BY_EXT,
    SCAN_ROOT_FILES,
    needs_slash_normalization,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

# Obsoleted-term declarations

# The retired-name catalogue is data that grows with every retirement;
# it lives beside this scanner rather than inside it.
from yoke_project_checks import _obsoleted_terms_catalog as _catalog
from yoke_project_checks._obsoleted_terms_catalog import (  # noqa: F401
    OBSOLETED_TERM_LABELS,
    OBSOLETED_TERM_PATTERNS,
    _PER_PATTERN_PATH_ALLOWLIST,
)

_SELF_PATH = Path(__file__).resolve()
# The catalogue spells every retired name out as a literal, so it is as
# self-referential as the scanner and carries the same exemption.
_CATALOG_PATH = Path(_catalog.__file__).resolve()
_SELF_NAMES = frozenset({_SELF_PATH.name, _CATALOG_PATH.name})


def _is_exempt(path: Path) -> bool:
    if path.resolve() in {_SELF_PATH, _CATALOG_PATH}:
        return True
    # Synthetic copies of the registry file (used by HC self-exemption tests)
    # carry the same filename but live under a tmp_path tree. The exemption
    # tracks the registry's identity, not its absolute location.
    if path.name in _SELF_NAMES:
        return True
    for part in path.parts:
        if part in EXEMPT_PATH_SEGMENTS:
            return True
    return False


def _path_in_allowlist(rel_str: str, allow: tuple[str, ...]) -> bool:
    """Return True when ``rel_str`` is covered by any allow-list entry.

    Matching is prefix-based, so one entry can cover a file family while a
    fully-qualified entry can target one exact path.
    """
    return any(rel_str.startswith(entry) for entry in allow)


def _iter_scan_paths(repo_root: Path):
    for name in SCAN_ROOT_FILES:
        candidate = repo_root / name
        if candidate.is_file() and not _is_exempt(candidate):
            yield candidate
    for ext, dirs in SCAN_DIRS_BY_EXT.items():
        for rel in dirs:
            base = repo_root / rel
            if not base.is_dir():
                continue
            try:
                discovered = list(base.rglob(f"*{ext}"))
            except OSError:
                # Concurrent xdist wheel builds can delete ``build/`` trees mid-walk.
                continue
            for f in discovered:
                try:
                    if _is_exempt(f):
                        continue
                except OSError:
                    continue
                yield f


def scan_repo(repo_root: Path) -> list[str]:
    """Return ``path:line: text`` strings where an obsoleted term matched.

    Exposed so tests and operator tooling can run the same scan used by the HC.

    The registry stores module-path patterns in dotted form
    (``runtime\\.harness\\.session_hooks``). Live-code regressions often appear
    in slash form — string-literal paths like
    ``"runtime/harness/codex/codex_hooks_tool_events.py"`` — so for those
    patterns each line is matched against both the original text and its
    slash-to-dot translation. The reported text is always the original line.
    """
    hits: list[str] = []
    compiled = [(pat, re.compile(pat)) for pat in OBSOLETED_TERM_PATTERNS]
    for f in _iter_scan_paths(repo_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        try:
            rel = f.resolve().relative_to(repo_root.resolve())
        except ValueError:
            rel = f
        rel_str = str(rel)
        if _path_in_allowlist(rel_str, PATH_ALLOWLIST_ALL_PATTERNS):
            continue
        for pattern_src, compiled_pattern in compiled:
            allow = _PER_PATTERN_PATH_ALLOWLIST.get(pattern_src, ())
            if _path_in_allowlist(rel_str, allow):
                continue
            normalize = needs_slash_normalization(pattern_src)
            label = OBSOLETED_TERM_LABELS.get(pattern_src, pattern_src)
            for i, line in enumerate(lines, start=1):
                if compiled_pattern.search(line):
                    hits.append(f"{rel}:{i}: [{label}] {line.rstrip()[:160]}")
                elif normalize and compiled_pattern.search(line.replace("/", ".")):
                    hits.append(f"{rel}:{i}: [{label}] {line.rstrip()[:160]}")
    return hits


def hc_obsoleted_terms(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-obsoleted-terms: obsoleted surface names in live prose."""
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(
            "HC-obsoleted-terms",
            "Obsoleted terms in live files",
            "PASS",
            "No repo root resolved — skipping.",
        )
        return
    repo_root = Path(repo_root_str)
    hits = scan_repo(repo_root)
    hits.extend(
        scan_backlog_fields(conn, OBSOLETED_TERM_PATTERNS, OBSOLETED_TERM_LABELS)
    )
    if hits:
        rec.record(
            "HC-obsoleted-terms",
            "Obsoleted terms in live files",
            "WARN",
            "\n".join(hits[:40]),
        )
    else:
        rec.record(
            "HC-obsoleted-terms",
            "Obsoleted terms in live files",
            "PASS",
            "",
        )

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ('obsoleted-terms', 'Obsoleted terms in live files', hc_obsoleted_terms),
)
