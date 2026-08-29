"""HC-unreachable-vocabulary-value: admitted values nothing can produce.

``HC-obsoleted-terms`` catches a reference to a surface that was deleted: the
name no longer resolves, so something dangles. This is its inverse. A feature
can be removed while its constant, its membership in a closed vocabulary, and
the branch comparing against it all survive. Nothing dangles — every reference
still resolves — and the value simply becomes one no live code path produces.

That is not cosmetic. A comparison which can never be true still occupies an
``if``/``elif`` arm, and the arms after it stop being reached for the inputs the
dead one claims. The instance this was built from rendered blank session cards
on two of three harnesses, traced back to an incomplete removal months earlier.

The vocabularies are declared by the database, so nothing here is
hand-maintained: every ``CHECK (col = ANY (ARRAY['a','b',...]))`` constraint
states the complete set of values one column may hold. A value is reachable on
any one of three kinds of evidence, each of which can only clear a value and
never flag one: a **stored row** already carries it; a **literal writer**
spells it in live source outside vocabulary and DDL declarations, including
inside SQL strings; or a **named producer** uses a module-level constant bound
to it somewhere that is neither a comparison nor the vocabulary declaration.
Only a value with none of the three, whose definition still survives in the
source tree, is reported — a value the source no longer mentions is
database-only residue with no definition left to remove.

Pairing source evidence with stored rows is what separates "no writer because
the value is dead" from "no writer because the writer is the outside world".
The bias throughout is toward silence, and posture is ``WARN``, because a value
may be admitted deliberately and the answer is sometimes to record why rather
than to delete — but that answer has to be written down, which is what the
warning asks for. Why this shape rather than the broader "enum member nothing
assigns" scan, and what that broader scan measured, is recorded in
``docs/archive/decisions/unreachable-vocabulary-value-detection.md``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)
from yoke_project_checks._vocabulary_evidence import source_evidence

HC_SLUG = "unreachable-vocabulary-value"
HC_LABEL = "Vocabulary values nothing can produce"
HC_ID = f"HC-{HC_SLUG}"

_COLUMN_RE = re.compile(r"\(\(?([a-z_][a-z0-9_]*) = ANY")
_VALUE_RE = re.compile(r"'([^']+)'::text")
_DDL_MARKERS = ("CHECK(", "CHECK (")


def constraint_vocabularies(conn: Any) -> List[Tuple[str, str, str]]:
    """Return ``(table, column, value)`` for every CHECK-declared vocabulary.

    Exposed so tests and operator tooling can read the same vocabulary set the
    check evaluates.
    """
    rows = conn.execute(
        "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE contype = 'c'"
    ).fetchall()
    found: List[Tuple[str, str, str]] = []
    for row in rows:
        table, definition = str(row[0]), str(row[1])
        column = _COLUMN_RE.search(definition)
        if not column:
            continue
        for value in _VALUE_RE.findall(definition):
            found.append((table, column.group(1), value))
    return found


def _by_value(pairs: list) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for value, site in pairs:
        grouped.setdefault(value, []).append(site)
    return grouped


def _stored_rows(conn: Any, table: str, column: str, value: str) -> int:
    row = conn.execute(
        f'SELECT count(*) FROM "{table}" WHERE "{column}"::text = %s', (value,)
    ).fetchone()
    return int(row[0])


def unreachable_values(conn: Any, repo_root: Path) -> List[str]:
    """Return one report line per admitted value nothing can produce."""
    vocabulary = constraint_vocabularies(conn)
    if not vocabulary:
        return []
    evidence = source_evidence(repo_root, {v for _, _, v in vocabulary})
    produced = _by_value(evidence["produced"])
    mentioned = _by_value(evidence["mentioned"])
    declared = _by_value(evidence["declared"])
    compared = _by_value(evidence["compared"])
    findings: List[str] = []
    for table, column, value in sorted(set(vocabulary)):
        if produced.get(value) or not mentioned.get(value):
            continue
        if _stored_rows(conn, table, column, value):
            continue
        where = sorted(set(declared.get(value) or mentioned.get(value)))
        readers = sorted(set(compared.get(value) or []))
        findings.append(
            f"{table}.{column} admits {value!r}, which no live code path can "
            f"produce and no stored row carries."
            f"\n    surviving definition: {', '.join(where)}"
            + (
                f"\n    comparison-only readers: {', '.join(readers)}"
                if readers
                else ""
            )
            + "\n    Remediation: delete the definition, its vocabulary "
            "membership, and every comparison against it. If the value must "
            "stay admitted, record why beside the declaration, the way "
            "RETIRED_PROJECT_KEYS does."
        )
    return findings


def hc_unreachable_vocabulary_value(
    conn: Any, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Vocabulary values nothing can produce."""
    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(HC_ID, HC_LABEL, "PASS", "No repo root resolved — skipping.")
        return
    findings = unreachable_values(conn, Path(repo_root))
    if not findings:
        rec.record(HC_ID, HC_LABEL, "PASS", "")
        return
    rec.record(HC_ID, HC_LABEL, "WARN", "\n".join(findings))


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (HC_SLUG, HC_LABEL, hc_unreachable_vocabulary_value),
)
