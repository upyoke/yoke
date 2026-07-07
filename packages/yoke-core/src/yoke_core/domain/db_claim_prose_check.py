"""Prose-vs-claim consistency detector for the unified DB-claim workflow.

Front door for the gate that ``/yoke refine``, ``/yoke advance``, and
``/yoke polish`` consult before allowing forward progress.  When the
spec/body of an item names governed DB mutation while the stored
``db_mutation_profile.state`` is still ``"none"``, the gate blocks and
points the caller at the canonical amendment surface
(``python3 -m yoke_core.api.service_client db-claim-amend``).

This file owns the public composition surface:

* :class:`ProseClaimCheck` — the verdict shape returned to callers.
* :func:`check` — detection-plus-claim composition over a prose string.
* :func:`check_item` — convenience wrapper that reads prose + claim from
  the DB.
* :func:`_cli_main` — ``python3 -m yoke_core.domain.db_claim_prose_check``
  entrypoint with ``check-item`` and ``detect`` subcommands.

The detection vocabulary and code-strip regexes live in
:mod:`yoke_core.domain.db_claim_prose_check_triggers`. Claim-state
readers (including the reviewed-negative attestation reader) live in
:mod:`yoke_core.domain.db_claim_prose_check_state`.

Escape hatches that clear the gate when prose triggers do fire:

* ``db_mutation_profile.state == "declared"`` — the ticket has already
  declared a governed DB mutation through the amendment workflow.
* In-spec negative scope note — clears only when no structural DDL-shape
  trigger fires.  Meta-tickets about DB governance that unavoidably cite
  DDL verbs cannot rely on this alone.
* Reviewed-negative attestation — when the stored profile carries
  ``state == "none"`` with ``reviewed_negative: true`` (stamped by the
  ``db_claim.amend`` workflow at amendment time), the gate treats the
  ticket as operator-reviewed no-DB work and clears even structural
  hits.  The ``DbClaimAmended`` events ledger is telemetry/audit only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from yoke_core.domain.db_claim_prose_check_state import (
    _claim_is_declared,
    _claim_reviewed_negative,
)
from yoke_core.domain.db_claim_prose_check_triggers import (
    _STRUCTURAL_TRIGGER_LABELS,
    _has_explicit_negative_db_claim,
    detect_triggers,
)


@dataclass(frozen=True)
class ProseClaimCheck:
    """Outcome of :func:`check`.

    ``triggers`` lists the human-readable labels of every rule that
    fired against the prose.  ``has_declared_claim`` reflects the
    stored profile state at the time of the check.  ``blocks`` is the
    composed verdict — true when prose names DB mutation but the claim
    is still ``state="none"`` and no explicit reviewed-negative signal
    is present.

    ``recovery`` carries a single operator-facing line describing how to
    amend the claim; empty when ``blocks`` is False.

    ``reviewed_negative_claim_detected`` is true when the stored profile
    records an explicit reviewed-none decision (``state == "none"`` plus
    the ``reviewed_negative: true`` attestation the amendment workflow
    stamps).  That signal suppresses vocabulary-only AND structural
    prose hits — meta-tickets about DB governance can discuss ``ALTER
    TABLE`` / ``ADD COLUMN`` plainly once an operator has amended the
    claim through the sanctioned workflow.
    """

    triggers: List[str]
    has_declared_claim: bool
    blocks: bool
    recovery: str = ""
    matched_snippets: List[str] = field(default_factory=list)
    negative_claim_detected: bool = False
    reviewed_negative_claim_detected: bool = False


def _build_recovery_line(item_id: Optional[int], triggers: Sequence[str]) -> str:
    target = f"YOK-{item_id}" if item_id is not None else "YOK-N"
    quoted = ", ".join(f"'{t}'" for t in triggers[:3])
    if len(triggers) > 3:
        quoted += ", ..."
    return (
        f"prose names governed DB mutation ({quoted}) but the stored "
        f"db_mutation_profile is state='none'.  Amend the DB claim before "
        f"advancing: python3 -m yoke_core.api.service_client db-claim-amend "
        f"--item {target} --reason \"<why>\" --payload '<unified-claim-json>'"
    )


def check(
    prose: str,
    *,
    profile_raw: Any = None,
    item_id: Optional[int] = None,
) -> ProseClaimCheck:
    """Compose prose detection and claim-state read into a single verdict.

    *prose* is the merged textual content the caller wants checked
    (typically ``spec``, ``body``, or a concatenation of structured
    fields).  *profile_raw* is the stored ``db_mutation_profile`` JSON;
    pass ``None`` when the caller wants pure detection without claim
    composition.  *item_id* is used only to format the recovery line.

    The reviewed-negative signal is read straight off *profile_raw*: a
    ``state="none"`` profile carrying the ``reviewed_negative: true``
    attestation (stamped by the ``db_claim.amend`` workflow) clears the
    gate even in the presence of structural DDL-shape triggers.  That
    branch exists so meta-tickets about DB governance can discuss
    ``ALTER TABLE`` / ``ADD COLUMN`` / ``migration_audit`` plainly once
    an operator has recorded an explicit reviewed-none decision through
    the unified amendment workflow.
    """
    triggers = detect_triggers(prose)
    labels = [t[0] for t in triggers]
    snippets = [t[1] for t in triggers]
    has_declared = _claim_is_declared(profile_raw)
    structural_hit = any(label in _STRUCTURAL_TRIGGER_LABELS for label in labels)
    negative_claim_detected = (
        bool(labels)
        and not structural_hit
        and _has_explicit_negative_db_claim(prose)
    )
    reviewed_negative = _claim_reviewed_negative(profile_raw)
    blocks = (
        bool(labels)
        and not has_declared
        and not negative_claim_detected
        and not reviewed_negative
    )
    recovery = _build_recovery_line(item_id, labels) if blocks else ""
    return ProseClaimCheck(
        triggers=labels,
        has_declared_claim=has_declared,
        blocks=blocks,
        recovery=recovery,
        matched_snippets=snippets,
        negative_claim_detected=negative_claim_detected,
        reviewed_negative_claim_detected=reviewed_negative,
    )


def check_item(
    item_id: int,
    *,
    fields: Optional[Sequence[str]] = None,
    conn=None,
) -> ProseClaimCheck:
    """Convenience wrapper that reads prose + claim from the DB.

    *fields* lists which structured columns to concatenate as the prose
    surface.  Defaults to ``("spec", "design_spec", "technical_plan",
    "worktree_plan", "shepherd_caveats")`` — the operator-authored
    surfaces that can declare DB work.  Generated/internal columns such
    as ``test_results`` and ``deploy_log`` are excluded by default.

    *conn* lets callers reuse an existing DB handle; when ``None`` the
    helper opens a short-lived connection via
    :func:`yoke_core.domain.db_helpers.connect`.
    """
    from yoke_core.domain import db_backend, db_helpers

    if fields is None:
        fields = (
            "spec",
            "design_spec",
            "technical_plan",
            "worktree_plan",
            "shepherd_caveats",
        )

    def _do(c) -> ProseClaimCheck:
        cols = list(fields) + ["db_mutation_profile"]
        col_list = ", ".join(cols)
        marker = "%s" if db_backend.connection_is_postgres(c) else "?"
        row = c.execute(
            f"SELECT {col_list} FROM items WHERE id = {marker}",
            (item_id,),
        ).fetchone()
        if row is None:
            return ProseClaimCheck(
                triggers=[], has_declared_claim=False, blocks=False
            )
        prose_chunks: List[str] = []
        for col in fields:
            value = row[col] if hasattr(row, "keys") else row[cols.index(col)]
            if value:
                prose_chunks.append(str(value))
        prose = "\n\n".join(prose_chunks)
        profile_raw = (
            row["db_mutation_profile"]
            if hasattr(row, "keys")
            else row[cols.index("db_mutation_profile")]
        )
        return check(
            prose,
            profile_raw=profile_raw,
            item_id=item_id,
        )

    if conn is not None:
        return _do(conn)
    with db_helpers.connect() as owned:
        return _do(owned)


def _cli_main(argv: Optional[Sequence[str]] = None) -> int:
    """``python3 -m yoke_core.domain.db_claim_prose_check`` entrypoint.

    Two subcommands::

        check-item <YOK-N>   Read prose + claim from the DB and emit a
                             JSON verdict. Exit 0 when the prose is
                             clean or the claim is already declared;
                             exit 2 when prose names DB work but the
                             stored profile is state='none'.

        detect <-|FILE>      Pure detection over a prose string read
                             from stdin or a path. Emits the same JSON
                             verdict shape; exit 0 always.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.db_claim_prose_check",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("check-item", help="Run check_item against a stored item.")
    check_p.add_argument("item", help="Backlog item ref (PREFIX-N).")

    detect_p = sub.add_parser("detect", help="Pure detection over prose from stdin or file.")
    detect_p.add_argument(
        "source", nargs="?", default="-",
        help="Path to read, or '-' for stdin. Defaults to stdin.",
    )

    args = parser.parse_args(argv)

    if args.cmd == "check-item":
        raw = args.item.strip()
        if raw.upper().startswith("YOK-"):
            raw = raw[4:]
        try:
            item_id = int(raw)
        except ValueError:
            print(json.dumps({
                "success": False,
                "code": "USAGE",
                "message": f"invalid item id {args.item!r}",
            }), file=sys.stderr)
            return 2
        outcome = check_item(item_id)
        payload = {
            "success": True,
            "item_id": item_id,
            "blocks": outcome.blocks,
            "triggers": outcome.triggers,
            "has_declared_claim": outcome.has_declared_claim,
            "negative_claim_detected": outcome.negative_claim_detected,
            "reviewed_negative_claim_detected": (
                outcome.reviewed_negative_claim_detected
            ),
            "matched_snippets": outcome.matched_snippets,
            "recovery": outcome.recovery,
        }
        print(json.dumps(payload))
        return 2 if outcome.blocks else 0

    if args.cmd == "detect":
        if args.source == "-":
            prose = sys.stdin.read()
        else:
            from pathlib import Path
            prose = Path(args.source).read_text(encoding="utf-8")
        triggers = detect_triggers(prose)
        payload = {
            "success": True,
            "triggers": [t[0] for t in triggers],
            "matched_snippets": [t[1] for t in triggers],
        }
        print(json.dumps(payload))
        return 0

    return 0


__all__ = [
    "ProseClaimCheck",
    "check",
    "check_item",
    "detect_triggers",
]


if __name__ == "__main__":
    raise SystemExit(_cli_main())
