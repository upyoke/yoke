"""MASTER-PLAN.md frontier order + prerequisite validator.

This module lets strategize explicitly validate two concrete things
against live backlog state:

1. **Ordered frontier entries** listed under
   ``## 5. Backlog By Generation`` > ``#### Remaining frontier``. The
   order encodes the operator's intended sequencing. If a later-ordered
   item is materially ahead of an earlier-ordered enabling item, that is
   ordered-frontier drift.
2. **Prerequisite/enabling prose** — sentences that use relationship
   language ("prerequisite", "depends on", "built on", "must not
   outrun", etc.) alongside two or more ``YOK-N`` refs. If the prose
   says ``YOK-A`` depends on ``YOK-B``, but live status reality shows
   ``YOK-A`` past ``YOK-B``, that is prerequisite-prose drift.

The module is **read-only**. It never mutates the plan, the DB, or any
item. It returns a structured result that strategize can render, or
falls through to advisory output when inputs are ambiguous.

Entry-point of a parser/evaluator/reporter triplet. Owns dataclasses,
the status-rank scale, ``lookup_statuses``, ``run_validation``, and the
CLI. Sibling modules ``master_plan_check_parse``,
``master_plan_check_evaluate``, and ``master_plan_check_render`` are
re-exported below.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect


# Status ranking: collapse the issue-workflow lifecycle plus a coarse
# epic rank into one ranked scale. The validator only cares about which
# item has moved further toward delivery, not the exact state names.
_STATUS_RANK: Dict[str, int] = {
    "idea": 0,
    "refining-idea": 1,
    "refined-idea": 2,
    "planning": 3,
    "plan-drafted": 4,
    "refining-plan": 5,
    "planned": 6,
    "implementing": 7,
    "reviewing-implementation": 8,
    "reviewed-implementation": 9,
    "polishing-implementation": 10,
    "implemented": 11,
    "release": 12,
    "done": 13,
}

# Exceptional/orthogonal states get a neutral "no rank" (no false-positive
# ordered-frontier hits). "blocked" is legacy drift here.
_EXCEPTIONAL_STATES = {"blocked", "stopped", "failed", "cancelled"}


def status_rank(status: Optional[str]) -> Optional[int]:
    """Return the canonical rank for *status*.

    Unknown or exceptional states return ``None`` — callers should treat
    those as "no ordering signal" and skip the pair.
    """
    if not status:
        return None
    if status in _EXCEPTIONAL_STATES:
        return None
    return _STATUS_RANK.get(status)


# Parsed shapes — these cross parser/evaluator/render boundaries.


@dataclass(frozen=True)
class FrontierEntry:
    """One parsed entry from an ordered frontier section.

    ``rank`` is 1-based within ``section`` (``remaining`` or ``landed``).
    ``title`` is best-effort and may be empty. ``raw_line`` preserves
    the original markdown line the entry was parsed from.
    """

    rank: int
    yok_id: str
    title: str
    section: str
    raw_line: str


@dataclass(frozen=True)
class ProseRelationship:
    """One prerequisite relationship extracted from plan prose.

    ``dependent`` builds on / depends on / requires ``blocker``;
    ``keyword`` is the matched relationship phrase; ``snippet`` is the
    raw sentence the relationship came from.
    """

    dependent: str
    blocker: str
    keyword: str
    snippet: str


@dataclass(frozen=True)
class Contradiction:
    """One concrete contradiction surfaced by the validator.

    ``kind`` is ``ordered_frontier_drift`` or ``prerequisite_prose_drift``.
    ``earlier`` is the enabling/earlier-ordered YOK-N; ``later`` is the
    dependent/later-ordered YOK-N. ``detail`` is the human-readable
    explanation of why the drift matters.
    """

    kind: str
    earlier: str
    earlier_status: str
    later: str
    later_status: str
    detail: str


@dataclass
class ValidationResult:
    """Full validator output.

    ``ambiguous_relationships`` is sentences with ≥3 YOK-refs around a
    prerequisite keyword — surfaced as advisory, not drift.
    ``advisories`` are soft warnings (missing section, partial parse,
    unknown YOK-N, etc.).
    """

    remaining_entries: List[FrontierEntry] = field(default_factory=list)
    landed_entries: List[FrontierEntry] = field(default_factory=list)
    relationships: List[ProseRelationship] = field(default_factory=list)
    ambiguous_relationships: List[ProseRelationship] = field(default_factory=list)
    contradictions: List[Contradiction] = field(default_factory=list)
    advisories: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "remaining_entries": [e.__dict__ for e in self.remaining_entries],
            "landed_entries": [e.__dict__ for e in self.landed_entries],
            "relationships": [r.__dict__ for r in self.relationships],
            "ambiguous_relationships": [r.__dict__ for r in self.ambiguous_relationships],
            "contradictions": [c.__dict__ for c in self.contradictions],
            "advisories": list(self.advisories),
        }


# Sibling re-exports — must come AFTER dataclass definitions so the parse /
# evaluate / render modules can import the shapes during their own load.
from yoke_core.domain.master_plan_check_parse import (  # noqa: E402
    parse_frontier_entries,
    parse_prerequisite_prose,
)
from yoke_core.domain.master_plan_check_evaluate import (  # noqa: E402
    validate_frontier_order,
    validate_prerequisite_prose,
)
from yoke_core.domain.master_plan_check_render import render_report  # noqa: E402


# DB lookup


def lookup_statuses(
    conn: Any,
    yok_ids: List[str],
) -> Dict[str, Optional[str]]:
    """Return ``{PREFIX-N: status-or-None}`` for each public ref.

    Resolution goes through the canonical public-ref parser
    (``yok_n_parser.parse_item_id``) so any project's prefix resolves
    via its ``public_item_prefix`` and per-project sequence — never a
    raw ``items.id`` guess. Unresolvable refs map to ``None``; the
    caller decides how to surface that (advisory vs drift).
    """
    if not yok_ids:
        return {}
    from yoke_core.domain.yok_n_parser import parse_item_id

    internal_by_ref: Dict[str, int] = {}
    for sid in yok_ids:
        try:
            internal_by_ref[sid] = parse_item_id(
                sid, conn=conn, allow_bare_internal=False,
            )
        except Exception:
            # Read-only advisory validator: an unresolvable ref (unknown
            # prefix, missing row, or a DB without identity tables) maps
            # to None — never a crash.
            continue

    if not internal_by_ref:
        return {sid: None for sid in yok_ids}

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    ids = sorted(set(internal_by_ref.values()))
    placeholders = ",".join(p for _ in ids)
    try:
        rows = conn.execute(
            f"SELECT id, status FROM items WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return {sid: None for sid in yok_ids}

    row_map = {int(r[0]): r[1] for r in rows}
    result: Dict[str, Optional[str]] = {}
    for sid, int_id in internal_by_ref.items():
        result[sid] = row_map.get(int_id)
    # Non-resolvable ids still map to None
    for sid in yok_ids:
        result.setdefault(sid, None)
    return result


# Orchestrator


def run_validation(
    md_text: str,
    conn: Optional[Any],
) -> ValidationResult:
    """Run full parse + DB-backed validation.

    If *conn* is ``None`` (no DB available), parser results are
    returned with an advisory; no contradictions are surfaced because
    we cannot verify statuses.
    """
    result = ValidationResult()
    remaining, landed, parse_advisories = parse_frontier_entries(md_text)
    result.remaining_entries = remaining
    result.landed_entries = landed
    result.advisories.extend(parse_advisories)

    unambig, ambig, prose_advisories = parse_prerequisite_prose(md_text)
    result.relationships = unambig
    result.ambiguous_relationships = ambig
    result.advisories.extend(prose_advisories)

    if conn is None:
        result.advisories.append(
            "No DB connection available — returning parser output only; "
            "strategize cannot verify live statuses."
        )
        return result

    # Gather all YOK-N ids we need to look up.
    yok_ids: List[str] = []
    seen: set[str] = set()
    for entry in remaining:
        if entry.yok_id not in seen:
            yok_ids.append(entry.yok_id)
            seen.add(entry.yok_id)
    for rel in unambig:
        for sid in (rel.dependent, rel.blocker):
            if sid not in seen:
                yok_ids.append(sid)
                seen.add(sid)

    statuses = lookup_statuses(conn, yok_ids)

    frontier_contras, frontier_adv = validate_frontier_order(remaining, statuses)
    prose_contras, prose_adv = validate_prerequisite_prose(unambig, statuses)

    result.contradictions.extend(frontier_contras)
    result.contradictions.extend(prose_contras)
    result.advisories.extend(frontier_adv)
    result.advisories.extend(prose_adv)

    return result


# CLI


def _default_plan_path() -> str:
    workspace = os.environ.get("YOKE_REPO_ROOT") or os.getcwd()
    from yoke_core.domain.strategy_docs_paths import strategy_view_path

    return str(strategy_view_path(workspace, "MASTER-PLAN"))


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.master_plan_check",
        description=(
            "Validate MASTER-PLAN.md frontier order and prerequisite "
            "prose against live backlog state."
        ),
    )
    parser.add_argument("--plan-path", help="Path to MASTER-PLAN.md (default: the rendered view under $YOKE_REPO_ROOT/.yoke/strategy/)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of a markdown report.")
    parser.add_argument("--exit-nonzero-on-drift", action="store_true", help="Exit non-zero when any contradiction is found (for CI gating).")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    plan_path = args.plan_path or _default_plan_path()
    if not os.path.exists(plan_path):
        msg = f"MASTER-PLAN.md not found at {plan_path}"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            print(msg)
        return 2

    with open(plan_path, "r", encoding="utf-8") as fh:
        md_text = fh.read()

    # Read live statuses from the Postgres control-plane authority. When the
    # backend is unreachable, fall through to parser-only advisory output.
    conn: Optional[Any] = None
    try:
        conn = connect()
    except Exception:
        conn = None

    try:
        result = run_validation(md_text, conn)
    finally:
        if conn is not None:
            conn.close()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_report(result))

    if args.exit_nonzero_on_drift and result.contradictions:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
