"""Doctor HC: correlate an events row by a column, never by an envelope scan.

Background
----------
``events.envelope`` is a JSON text column with no index over its contents.
A query that finds a row by matching a substring of that text has to read
and match every row the rest of its predicates admit, and the ``events``
table is the largest in the system. On 2026-09-04 a hook telemetry lookup
of exactly this shape — a client-supplied id matched with ``envelope LIKE``
over a thirty-day window — held tens of concurrent multi-minute scans on
production, blocked the updates behind them, and took the connection pool
with it. Every relayed call queued for the thirty-five minutes it lasted.

Contract
--------
Executable SQL matching ``events.envelope`` with LIKE or ILIKE must be on
the allowlist below, and each entry names the indexed key that bounds the
rows the match is applied to. Unbounded is the failure: the pool outage came
from an envelope match with nothing but a thirty-day date range in front of
it. A value the request path has to find gets its own indexed column
(``client_timing_id`` is the worked example) and equality instead.

The scan reads executable string literals only, so the docstrings, comments,
and denial messages that TEACH this rule are not themselves violations —
otherwise rewording the teaching would look like fixing the defect.

Maintenance
-----------
A new entry names its bounding key in the inline comment, or it does not
belong here. Request-path code does not qualify however narrow its bound:
an operator-invoked audit absorbs a slow scan on one connection, and a hook
running on every tool call does not. Stale entries surface in the PASS
detail so a removed reader cleans up its row.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_tree_scan import GENERATED_TREE_NAMES, iter_tree_files
from yoke_project_checks._sql_literal_scan import (
    python_literal_strings,
    sql_executable_text,
)


HC_NAME = "HC-events-envelope-like-scan"
HC_DESC = "Events rows are correlated by an indexed column, not an envelope scan"

SCAN_ROOTS = ("packages", "runtime", ".yoke/doctor")

_CORE_DOMAIN_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/domain"

# Repo-relative allowlist. Each entry names the indexed key bounding the
# rows the envelope match runs over.
ALLOWED_ENVELOPE_LIKE_READERS: tuple[str, ...] = (
    # Claim-boundary audit: bounded by the indexed `event_name` plus the
    # audit's configured `events.id` cutoff, and reached only from an
    # operator-invoked doctor run, never from a request path.
    f"{_CORE_DOMAIN_SOURCE_ROOT}/check_claim_boundary_audit_select.py",
    # apply_patch smoke probe: bounded by the indexed `event_name`, and
    # reached only from an operator-invoked doctor run.
    ".yoke/doctor/check_apply_patch.py",
)

# ``envelope`` optionally cast, then LIKE/ILIKE — the unindexed substring
# match. Equality against the whole column is a different (and cheap) shape
# and stays out of scope.
_ENVELOPE_LIKE_RE = re.compile(
    r"\benvelope\b(?:\s*::\s*\w+)?\s+(?:NOT\s+)?I?LIKE\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EnvelopeLikeScan:
    """One executable statement matching envelope text with LIKE."""

    relpath: str
    line: int
    text: str


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _is_test_path(relative: Path) -> bool:
    name = relative.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if name == "conftest.py":
        return True
    return "tests" in relative.parts


def _scan_python(repo_root: Path, path: Path) -> List[EnvelopeLikeScan]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if "envelope" not in source.lower():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    relpath = path.relative_to(repo_root).as_posix()
    return [
        EnvelopeLikeScan(relpath=relpath, line=lineno, text=text.strip()[:160])
        for lineno, text in python_literal_strings(tree)
        if _ENVELOPE_LIKE_RE.search(text)
    ]


def _scan_sql(repo_root: Path, path: Path) -> List[EnvelopeLikeScan]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not _ENVELOPE_LIKE_RE.search(sql_executable_text(source)):
        return []
    relpath = path.relative_to(repo_root).as_posix()
    return [
        EnvelopeLikeScan(relpath=relpath, line=lineno, text=line.strip()[:160])
        for lineno, line in enumerate(source.splitlines(), start=1)
        if _ENVELOPE_LIKE_RE.search(sql_executable_text(line))
    ]


def _allowlisted(relpath: str) -> bool:
    return relpath in ALLOWED_ENVELOPE_LIKE_READERS


def _scanned_files(repo_root: Path, roots: Sequence[str]) -> Iterator[Path]:
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in sorted(
            (
                *iter_tree_files(base, "*.py", prune_dir_names=GENERATED_TREE_NAMES),
                *iter_tree_files(base, "*.sql", prune_dir_names=GENERATED_TREE_NAMES),
            )
        ):
            relative = path.relative_to(repo_root)
            if _is_test_path(relative):
                continue
            yield path


def scan_envelope_like_reads(
    repo_root: Path,
    *,
    roots: Optional[Sequence[str]] = None,
) -> tuple[List[EnvelopeLikeScan], List[str]]:
    """Return (violations, stale allowlist entries) for ``repo_root``."""
    findings: List[EnvelopeLikeScan] = []
    matched: set[str] = set()
    for path in _scanned_files(repo_root, roots if roots is not None else SCAN_ROOTS):
        scanned = (
            _scan_sql(repo_root, path)
            if path.suffix == ".sql"
            else _scan_python(repo_root, path)
        )
        seen: set[int] = set()
        for finding in scanned:
            if _allowlisted(finding.relpath):
                matched.add(finding.relpath)
                continue
            if finding.line in seen:
                continue
            seen.add(finding.line)
            findings.append(finding)
    stale = [e for e in ALLOWED_ENVELOPE_LIKE_READERS if e not in matched]
    return findings, stale


def hc_events_envelope_like_scan(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Doctor entry. FAILs when executable SQL scans envelope text."""
    findings, stale = scan_envelope_like_reads(_project_root())
    if not findings:
        detail = "No unbounded statement matches events.envelope with LIKE."
        if stale:
            detail += " Stale allowlist entries (no match found): " + ", ".join(stale)
        rec.record(HC_NAME, HC_DESC, "PASS", detail)
        return
    head = (
        f"- {len(findings)} executable statement(s) match `events.envelope` "
        "with LIKE outside the allowlist. An unindexed envelope match reads "
        "every row its other predicates admit; give the value its own indexed "
        "column (see `events.client_timing_id`) and match it by equality, or "
        "allowlist the reader naming the indexed key that bounds it."
    )
    body = "\n".join(
        [head, ""] + [f"  - `{f.relpath}:{f.line}`: {f.text}" for f in findings]
    )
    rec.record(HC_NAME, HC_DESC, "FAIL", body)


__all__ = [
    "ALLOWED_ENVELOPE_LIKE_READERS",
    "EnvelopeLikeScan",
    "HC_DESC",
    "HC_NAME",
    "SCAN_ROOTS",
    "hc_events_envelope_like_scan",
    "scan_envelope_like_reads",
]

from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "events-envelope-like-scan",
        HC_DESC,
        hc_events_envelope_like_scan,
    ),
)
