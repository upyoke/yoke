"""Record an explicitly supplied commit without replacing verified identity."""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

from yoke_core.domain.qa_merging_identity import recorded_head_sha


def wrap_evidence(raw_result: Optional[str], head_sha: str, root: str = "") -> str:
    """Keep prose as evidence and put the sha in verification_tree."""
    payload: dict[str, Any]
    try:
        loaded = json.loads(str(raw_result or ""))
    except (TypeError, ValueError):
        loaded = None
    if isinstance(loaded, dict):
        payload = dict(loaded)
    else:
        payload = {}
        evidence = str(raw_result or "").strip()
        if evidence:
            payload["evidence"] = evidence
    tree = payload.get("verification_tree")
    tree = dict(tree) if isinstance(tree, dict) else {}
    tree["head_sha"] = head_sha
    if root:
        tree.setdefault("root", root)
    payload["verification_tree"] = tree
    return json.dumps(payload, sort_keys=True)


def bind_recorded_raw_result(
    *, raw_result: Optional[str], head_sha: Optional[str] = None,
) -> Optional[str]:
    """Package an explicit observation; the run writer owns automatic capture."""
    if recorded_head_sha(raw_result) or not str(head_sha or "").strip():
        return raw_result
    return wrap_evidence(raw_result, str(head_sha).strip())


def bind_cli_raw_result(
    *,
    verdict: Optional[str],
    raw_result: Optional[str],
    performed_by: str,
    requirement_id: int,
    db_path: Optional[str] = None,
    head_sha: Optional[str] = None,
) -> Optional[str]:
    """CLI adapter: bind or ``sys.exit(2)`` with the named refusal."""
    from yoke_core.domain.db_helpers import connect, query_one

    conn = connect(path=db_path)
    try:
        row = query_one(
            conn,
            "SELECT blocking_mode, waived_at, item_id, method_config, runner_id, qa_phase, deployment_run_id "
            "FROM qa_requirements WHERE id = %s",
            (int(requirement_id),),
        )
        if row is None:
            print(
                f"Error: requirement_id {requirement_id} not found in qa_requirements",
                file=sys.stderr,
            )
            sys.exit(2)
        bound = bind_recorded_raw_result(raw_result=raw_result, head_sha=head_sha)
        from yoke_core.domain.qa_requirement_pass_currency import (
            stamp_executed_method_config,
        )

        return stamp_executed_method_config(
            bound,
            row["method_config"],
            conn=conn,
            requirement_id=int(requirement_id),
        )
    finally:
        conn.close()


__all__ = ["bind_cli_raw_result", "bind_recorded_raw_result", "wrap_evidence"]
