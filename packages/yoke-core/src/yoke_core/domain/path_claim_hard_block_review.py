"""Classifier for non-terminal ``activation`` dependency edges that look
like path-claim-only hard blocks lacking explicit directional evidence.

The cleanup pass observed activation rows whose rationale mentioned a
specific file or path overlap with an upstream claim, but did not
explicitly say the candidate work is order-dependent on the upstream
(no ``decision=directional`` evidence). Those rows over-block lifecycle:
the right shape is usually a ``coordination_only`` compatibility edge,
which lets both items activate and leaves any same-hunk collision to
normal merge-time conflict handling.

This module is the read-only review surface. It exposes:

- :class:`ActivationReview` — verdict + reason + remediation for one row.
- :func:`review_activation_row` — pure function over a row dict.
- :func:`scan_non_terminal_activation_rows` — DB-aware iterator that
  joins ``item_dependencies`` to ``items`` and returns the over-hard
  rows for downstream HCs/tests.

The classifier never mutates. The Doctor HC
(:mod:`yoke_core.engines.doctor_hc_path_claim_hard_blocks`) calls into
this module and renders WARN findings; the same module is consumed by
``runtime.api.domain.test_path_claim_hard_block_review`` for the
authored test cases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional

from yoke_core.domain.schema_common import _table_exists as _schema_table_exists


# Rows whose dependent item is in a final lifecycle state never need
# review — the activation edge has already done (or failed to do) its
# job. ``implemented`` / ``release`` are intentionally not terminal here:
# those items still have merge/deploy handoff remaining.
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "cancelled"})

# Sources commonly authored by the idea/refine path-claim conflict
# workflow. Activation rows from these sources, lacking directional
# evidence, are the cleanup target.
PATH_CLAIM_AUTHORING_SOURCES: frozenset[str] = frozenset({"idea", "refine"})

# Heuristic markers in rationale text. A rationale must include concrete
# path evidence — a repo file path/root file, or a structured shared_paths
# field — before the review treats it as path-claim hard-block authoring.
# Plain conceptual prose like "overlaps path-claim guidance" is too broad:
# those rows may encode legitimate sequencing between related tickets.
_PATH_EVIDENCE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bshared_paths?\s*=", re.IGNORECASE),
)
_FILEPATH_PATTERN: re.Pattern = re.compile(
    # naive file-path-like detection: at least one slash plus a known suffix,
    # OR a known root-level repo file
    r"(?:[A-Za-z0-9_.\-/]+/[A-Za-z0-9_.\-/]+\.(?:md|py|json|yaml|yml|toml|sh|ts|tsx|js|jsx))"
    r"|(?:\b(?:AGENTS|CLAUDE|README|CHANGELOG)\.md\b)"
)

# The literal token that proves directional intent. Authors include this
# in the rationale to attest that the candidate is order-dependent on the
# upstream landing first.
_DIRECTIONAL_TOKEN: str = "decision=directional"
# The literal token that proves coordination-only intent. If an
# activation row carries this, it is a clear mislabel.
_COORDINATION_TOKEN: str = "decision=coordination_only"


@dataclass
class ActivationReview:
    """Review verdict for a single activation row.

    Attributes:
        over_hard: True when the row looks like a path-claim-only hard
            block lacking directional evidence.
        reason: Short human-readable explanation of the verdict.
        remediation: Suggested follow-up for over-hard rows; empty
            string when ``over_hard=False``.
    """

    over_hard: bool
    reason: str
    remediation: str = ""


def _rationale_mentions_path(rationale: str) -> bool:
    """Return True when rationale text carries concrete path evidence."""
    if not rationale:
        return False
    if _FILEPATH_PATTERN.search(rationale):
        return True
    for pattern in _PATH_EVIDENCE_PATTERNS:
        if pattern.search(rationale):
            return True
    return False


def review_activation_row(
    *,
    gate_point: str,
    source: str,
    rationale: str,
    dependent_status: Optional[str] = None,
    blocking_status: Optional[str] = None,
) -> ActivationReview:
    """Classify one ``item_dependencies`` row.

    Pure function — no DB reads, no event emission. Callers supply the
    row's fields plus optional lifecycle context.
    """
    if gate_point != "activation":
        return ActivationReview(
            False,
            "not an activation edge — non-applicable",
        )

    if (dependent_status or "").lower() in TERMINAL_STATUSES:
        return ActivationReview(
            False,
            "dependent item is terminal — no remediation needed",
        )
    if (blocking_status or "").lower() in TERMINAL_STATUSES:
        return ActivationReview(
            False,
            "blocking item is terminal — dependency is already satisfied",
        )

    rationale_text = rationale or ""

    # Explicit directional attestation wins immediately: the rationale
    # names why order matters via the canonical token.
    if _DIRECTIONAL_TOKEN in rationale_text:
        return ActivationReview(
            False,
            "directional evidence present (decision=directional)",
        )

    # An activation row that carries the coordination_only token is a
    # clear mislabel — flag it explicitly.
    if _COORDINATION_TOKEN in rationale_text:
        return ActivationReview(
            True,
            "rationale says decision=coordination_only but gate_point is "
            "activation — convert the row via dependency-update --gate-point "
            "coordination_only",
            remediation=(
                "Update the row's gate_point to coordination_only; the "
                "rationale already records the independence decision."
            ),
        )

    # Path-claim-driven authoring intent: source is idea/refine and
    # rationale mentions concrete path evidence. Without directional
    # evidence, this is the cleanup-pass over-hard shape.
    source_normalized = (source or "").lower()
    if source_normalized in PATH_CLAIM_AUTHORING_SOURCES and _rationale_mentions_path(
        rationale_text
    ):
        return ActivationReview(
            True,
            "activation row authored from path-claim overlap "
            f"(source={source_normalized!r}, rationale includes path evidence) "
            "without decision=directional evidence",
            remediation=(
                "Re-classify via yoke claims path coordination-decision-build. If the "
                "edits are semantically independent, convert to "
                "--gate-point coordination_only; if order-dependent, add "
                "decision=directional to the rationale naming why order "
                "matters."
            ),
        )

    return ActivationReview(
        False,
        "no path-claim authoring signal detected — not flagged",
    )


@dataclass
class OverHardRow:
    """An over-hard activation row from a DB scan."""

    dependency_id: int
    dependent_item: str
    blocking_item: str
    source: str
    rationale: str
    dependent_status: str
    blocking_status: str
    review: ActivationReview


def scan_non_terminal_activation_rows(
    conn: Any,
) -> List[OverHardRow]:
    """Return the over-hard non-terminal activation rows from the DB.

    Joins ``item_dependencies`` to ``items`` to read lifecycle status
    for both endpoints, then applies :func:`review_activation_row` to
    each row. The result list contains only rows where
    ``review.over_hard`` is True. Empty when the DB has no
    ``item_dependencies`` table (minimal-schema fixtures).
    """
    if not _has_table(conn, "item_dependencies"):
        return []

    rows = conn.execute(
        "SELECT d.id, d.dependent_item, d.blocking_item, d.gate_point, "
        "d.source, d.rationale, "
        "  COALESCE(di.status, '') AS dependent_status, "
        "  COALESCE(bi.status, '') AS blocking_status "
        "FROM item_dependencies AS d "
        "LEFT JOIN items AS di ON di.id = "
        "  CAST(REPLACE(d.dependent_item, 'YOK-', '') AS INTEGER) "
        "LEFT JOIN items AS bi ON bi.id = "
        "  CAST(REPLACE(d.blocking_item, 'YOK-', '') AS INTEGER) "
        "WHERE d.gate_point = 'activation' "
        "ORDER BY d.id ASC"
    ).fetchall()

    out: List[OverHardRow] = []
    for row in rows:
        review = review_activation_row(
            gate_point="activation",
            source=_row_get(row, "source", 4),
            rationale=_row_get(row, "rationale", 5),
            dependent_status=_row_get(row, "dependent_status", 6),
            blocking_status=_row_get(row, "blocking_status", 7),
        )
        if not review.over_hard:
            continue
        out.append(
            OverHardRow(
                dependency_id=int(_row_get(row, "id", 0)),
                dependent_item=str(_row_get(row, "dependent_item", 1)),
                blocking_item=str(_row_get(row, "blocking_item", 2)),
                source=str(_row_get(row, "source", 4)),
                rationale=str(_row_get(row, "rationale", 5)),
                dependent_status=str(_row_get(row, "dependent_status", 6)),
                blocking_status=str(_row_get(row, "blocking_status", 7)),
                review=review,
            )
        )
    return out


def _has_table(conn: Any, table: str) -> bool:
    return _schema_table_exists(conn, table)


def _row_get(row, key: str, index: int):
    """Read a row by name when available, else by tuple index."""
    keys = row.keys() if hasattr(row, "keys") else ()
    if key in keys:
        return row[key]
    return row[index]


__all__ = [
    "ActivationReview",
    "OverHardRow",
    "PATH_CLAIM_AUTHORING_SOURCES",
    "TERMINAL_STATUSES",
    "review_activation_row",
    "scan_non_terminal_activation_rows",
]
