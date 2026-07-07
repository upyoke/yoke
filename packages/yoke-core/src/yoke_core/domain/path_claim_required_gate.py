"""Claim-required gate for /yoke idea and /yoke refine.

The gate is the single source of truth every claim-coverage caller
consults. Idea calls it after the draft item exists to decide
whether creation can proceed. Refine calls it before advancing past
``refining-idea`` (or ``refining-plan`` for epics). The catch-up
invariant
(:mod:`yoke_core.domain.path_integrity_invariants_claim_coverage`)
checks the same condition for every non-terminal item project-wide.

Coverage is satisfied when:

* The item has at least one non-terminal claim row
  (``state IN ('planned','blocked','active')``) with a non-exception
  mode and at least one ``path_claim_targets`` row, OR
* The item has at least one non-terminal claim row with
  ``mode='exception'`` and a non-empty ``exception_reason``.

Any other state — zero claims, only terminal claims, an exception row
with empty reason — fails the gate.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from yoke_core.domain import db_backend

_NON_TERMINAL_STATES = ("planned", "blocked", "active")


GATE_PASS = "pass"
GATE_BLOCK = "block"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def evaluate(
    conn: Any, item_id: int,
) -> Dict[str, object]:
    """Return ``{verdict, reason, satisfying_claims}`` for the gate.

    The verdict is ``"pass"`` or ``"block"``. The reason is operator-
    facing text the caller can surface verbatim. ``satisfying_claims``
    lists the claim ids that pass the gate (empty when blocked) so
    consumers can audit which row carried the coverage.
    """
    p = _p(conn)
    placeholders = ",".join(p for _ in _NON_TERMINAL_STATES)
    rows = conn.execute(
        f"""
        SELECT pc.id, pc.mode, COALESCE(TRIM(pc.exception_reason), '') AS reason,
               (
                 SELECT COUNT(*) FROM path_claim_targets pct
                  WHERE pct.claim_id = pc.id
               ) AS target_count
          FROM path_claims pc
         WHERE pc.item_id = {p}
           AND pc.state IN ({placeholders})
        ORDER BY pc.id
        """,
        (item_id, *_NON_TERMINAL_STATES),
    ).fetchall()
    satisfying: list[int] = []
    for row in rows:
        cid = int(row[0])
        mode = str(row[1])
        reason_text = str(row[2])
        target_count = int(row[3])
        if mode == "exception" and reason_text:
            satisfying.append(cid)
        elif mode != "exception" and target_count > 0:
            satisfying.append(cid)
    if satisfying:
        # Enrich the operator-facing reason when one or more
        # satisfying claims are themselves blocked on an upstream
        # path claim, naming the upstream item and its current
        # status so the operator sees one coherent diagnostic across
        # path_claim_required_gate and evaluate-gate.
        blocked_addenda = _describe_blocked_satisfying_claims(
            conn, satisfying,
        )
        base_reason = (
            f"item YOK-{item_id} has {len(satisfying)} satisfying "
            f"claim row(s)"
        )
        if blocked_addenda:
            reason = base_reason + " — " + "; ".join(blocked_addenda)
        else:
            reason = base_reason
        return {
            "verdict": GATE_PASS,
            "reason": reason,
            "satisfying_claims": satisfying,
        }
    return {
        "verdict": GATE_BLOCK,
        "reason": (
            f"item YOK-{item_id} has no non-terminal path claim and no "
            f"active no-claim exception. Register coverage with "
            f"`python3 -m yoke_core.api.service_client path-claim-register "
            f"--item YOK-{item_id} --integration-target main "
            f"--paths <comma-separated paths> [--allow-planned]` or "
            f"record a no-claim exception with `--mode exception "
            f"--reason \"<why this item touches no repo surface>\"`."
        ),
        "satisfying_claims": [],
    }


def is_satisfied(conn: Any, item_id: int) -> bool:
    """Return True iff :func:`evaluate` would return verdict='pass'.

    Convenience wrapper for callers that only need the boolean
    decision, e.g. the catch-up audit's per-item probe.
    """
    return evaluate(conn, item_id)["verdict"] == GATE_PASS


def items_missing_coverage(
    conn: Any, candidate_ids: Iterable[int],
) -> list[int]:
    """Return the subset of ``candidate_ids`` that fail the gate.

    Helper for tooling that wants to scan a curated list (e.g. the
    operator selection of "items I touched today") rather than the
    project-wide invariant. Accepts any iterable of bare integer
    item ids.
    """
    out: list[int] = []
    for raw in candidate_ids:
        item_id = int(raw)
        if not is_satisfied(conn, item_id):
            out.append(item_id)
    return out


def _describe_blocked_satisfying_claims(
    conn: Any, claim_ids: list[int],
) -> list[str]:
    """Render diagnostic strings for blocked satisfying claims.

    Returns one human-readable string per claim that is currently
    ``blocked``, naming the upstream path-claim id and (when resolvable)
    the upstream's owning item / status. Empty list when no claim is
    blocked, so the caller can fall through to today's plain reason.
    """
    out: list[str] = []
    p = _p(conn)
    for cid in claim_ids:
        row = conn.execute(
            f"SELECT state, blocked_reason FROM path_claims WHERE id = {p}",
            (cid,),
        ).fetchone()
        if row is None or str(row[0]) != "blocked":
            continue
        reason = str(row[1] or "")
        upstream_id = _extract_upstream_claim_id(reason)
        if upstream_id is None:
            out.append(f"path claim {cid} blocked: {reason or '(unknown)'}")
            continue
        upstream_row = conn.execute(
            "SELECT pc.item_id, COALESCE(i.status, '') FROM path_claims pc "
            "LEFT JOIN items i ON i.id = pc.item_id "
            f"WHERE pc.id = {p}",
            (upstream_id,),
        ).fetchone()
        if upstream_row is None:
            out.append(
                f"path claim {cid} blocked on path claim {upstream_id}"
            )
            continue
        up_item = upstream_row[0]
        up_status = upstream_row[1]
        if up_item is not None:
            out.append(
                f"path claim {cid} blocked on path claim {upstream_id} "
                f"(YOK-{int(up_item)}, status: {up_status or 'unknown'})"
            )
        else:
            out.append(
                f"path claim {cid} blocked on path claim {upstream_id}"
            )
    return out


def _extract_upstream_claim_id(blocked_reason: str) -> int | None:
    """Pull ``N`` out of ``serial-via-dependency on path_claims.id=N``."""
    if not blocked_reason:
        return None
    needle = "path_claims.id="
    idx = blocked_reason.find(needle)
    if idx < 0:
        return None
    tail = blocked_reason[idx + len(needle):].strip()
    digits = ""
    for ch in tail:
        if ch.isdigit():
            digits += ch
        else:
            break
    if not digits:
        return None
    return int(digits)


def _parse_item_id(raw: str) -> int:
    text = raw.strip()
    if text.upper().startswith("YOK-"):
        text = text[4:]
    return int(text.lstrip("0") or "0")


def main(argv: list[str] | None = None) -> int:
    """CLI surface so skill prose can call the gate directly.

    Usage::

        python3 -m yoke_core.domain.path_claim_required_gate YOK-N

    Prints a single JSON object with ``verdict`` / ``reason`` /
    ``satisfying_claims``. Exit code is 0 for ``pass`` and 1 for
    ``block`` so shell callers can branch on ``$?``.
    """
    import argparse
    import json
    import sys

    from yoke_core.domain import db_helpers

    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.path_claim_required_gate",
        description=(
            "Evaluate the path-claim-required gate for one item. Exit 0 "
            "when coverage is satisfied, 1 when blocked."
        ),
    )
    parser.add_argument("item", help="YOK-N or N")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        item_id = _parse_item_id(args.item)
    except ValueError as exc:
        print(json.dumps({"verdict": GATE_BLOCK, "reason": str(exc)}))
        return 2
    conn = db_helpers.connect()
    try:
        result = evaluate(conn, item_id)
    finally:
        conn.close()
    print(json.dumps(result))
    return 0 if result["verdict"] == GATE_PASS else 1


__all__ = [
    "GATE_BLOCK",
    "GATE_PASS",
    "evaluate",
    "is_satisfied",
    "items_missing_coverage",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
