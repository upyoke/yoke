"""Evidence-building helper for the LLM-agent coordination-only decision.

Gathers context an LLM agent needs to choose between ``coordination_only``,
directional ``activation``, or operator ``escalate`` for two overlapping
claims. Does NOT make the decision — semantic independence analysis is the
agent's job. The packet carries both specs, the conflicting claim's state,
shared-path metadata, and three ready-to-paste command lines (one per
decision option). Callers: ``runtime/agents/architect.md`` (intra-epic),
``.agents/skills/yoke/idea/path-claim-blocking.md`` (cross-item overlap
resolution), and ``.agents/skills/yoke/refine/readiness-repair.md``.
"""

from __future__ import annotations

from typing import Any, List, TypedDict

from yoke_core.domain import db_backend, runtime_settings
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.dependency_types import GatePoint
from yoke_core.domain.items_queries import query_item
from yoke_core.domain.path_registry import ancestors_of, target_at


_DEFAULT_SPEC_TRUNCATION_BYTES = 4096
_TRUNCATION_CONFIG_KEY = "coordination_context_spec_truncation_bytes"
_PROJECT_ID = "yoke"
DECISION_OPTIONS: List[str] = ["coordination_only", "directional", "escalate"]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class CoordinationContext(TypedDict):
    """Typed evidence packet for an LLM-agent coordination decision."""

    candidate_item_id: int
    candidate_spec: str
    conflicting_claim_id: int
    conflicting_item_id: int
    conflicting_item_spec: str
    conflicting_claim_state: str
    shared_paths: List[str]
    shared_path_metadata: List[dict]
    suggested_commands: List[str]
    decision_options: List[str]
    rationale_checklist: List[str]


def _truncation_limit() -> int:
    try:
        return runtime_settings.get_int(
            _TRUNCATION_CONFIG_KEY, _DEFAULT_SPEC_TRUNCATION_BYTES)
    except Exception:
        return _DEFAULT_SPEC_TRUNCATION_BYTES


def _read_spec(item_id: int) -> str:
    # query_item returns "" for missing rows AND present-but-NULL fields;
    # disambiguate by re-reading id (non-empty proves the row exists).
    spec = query_item(item_id, "spec")
    if spec != "":
        return spec
    if query_item(item_id, "id") == "":
        raise ValueError(f"item {item_id} not found")
    return ""


def _conflicting_claim_row(conn: Any, claim_id: int) -> dict:
    row = conn.execute(
        "SELECT id, state, item_id, integration_target FROM path_claims "
        f"WHERE id = {_p(conn)}", (claim_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"path_claim {claim_id} not found")
    return {
        "id": int(row["id"]), "state": str(row["state"]),
        "item_id": int(row["item_id"]) if row["item_id"] is not None else 0,
        "integration_target": str(row["integration_target"]),
    }


def _shared_path_metadata(
    conn: Any, shared_paths: List[str],
) -> List[dict]:
    out: List[dict] = []
    for path in shared_paths:
        target_id = target_at(conn, _PROJECT_ID, path)
        if target_id is None:
            out.append({"path": path, "kind": "unknown", "lineage_depth": 0})
            continue
        kind_row = conn.execute(
            f"SELECT kind FROM path_targets WHERE id = {_p(conn)}",
            (target_id,),
        ).fetchone()
        kind = str(kind_row["kind"]) if kind_row is not None else "unknown"
        out.append({"path": path, "kind": kind,
                    "lineage_depth": len(ancestors_of(conn, target_id))})
    return out


_RATIONALE_CHECKLIST: List[str] = [
    "decision=<coordination_only|directional|escalate>",
    "shared_paths=<comma-separated paths from the overlap>",
    "conflicting_claim_id=<the path_claims.id this row coordinates with>",
    "independence_evidence=<for coordination_only: which disjoint "
    "sections/functions each ticket edits; explicitly absent for directional>",
    "why_order_matters=<for directional: what upstream lands that the "
    "candidate inherits or restructures; explicitly absent for coordination_only>",
]


def _suggested_commands(
    cand_id: int, other_id: int, shared_paths: List[str],
    conflicting_claim_id: int,
) -> List[str]:
    cand, other = f"YOK-{cand_id}", f"YOK-{other_id}"
    co = GatePoint.COORDINATION_ONLY.value
    dep_add = "yoke shepherd dependency-add"
    shared = ",".join(shared_paths) if shared_paths else "<shared-paths>"
    coord_rationale = (
        f"decision=coordination_only. shared_paths={shared}. "
        f"conflicting_claim_id={conflicting_claim_id}. "
        "independence_evidence=<which disjoint sections each ticket edits>"
    )
    dir_rationale = (
        f"decision=directional. shared_paths={shared}. "
        f"conflicting_claim_id={conflicting_claim_id}. "
        "why_order_matters=<what upstream lands that the candidate inherits>"
    )
    return [
        f"# option: coordination_only (independent same-file edits, "
        "path-claim mutex with no lifecycle gate)",
        f"{dep_add} {cand} {other} <source> --gate-point {co} "
        f"--rationale \"{coord_rationale}\"",
        f"# option: directional activation (order-dependent edits, "
        "lifecycle gate + path-claim mutex)",
        f"{dep_add} {cand} {other} <source> --gate-point activation "
        f"--satisfaction fact:merged --rationale \"{dir_rationale}\"",
        f"# option: escalate (operator override, last resort)",
        "python3 -m yoke_core.api.service_client path-claim-override "
        f"--item {cand} --reason \"<operator-authored rationale per "
        "AGENTS.md ## Path Claims — Hard Rule>\"",
    ]


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


def build_coordination_context(
    conn: Any, *, candidate_item_id: int,
    conflicting_claim_id: int, shared_paths: List[str],
) -> CoordinationContext:
    """Gather the evidence packet for an LLM-agent coordination decision.

    LLM agents own the final call; this helper does NOT perform static
    semantic analysis. Spec reads use ``query_item`` (opens its own
    connection); ``conn`` is used only for ``path_claims`` /
    ``path_targets`` reads.
    """
    limit = _truncation_limit()
    cand_spec = _read_spec(candidate_item_id)
    claim = _conflicting_claim_row(conn, conflicting_claim_id)
    other_id = claim["item_id"]
    other_spec = _read_spec(other_id)
    return CoordinationContext(
        candidate_item_id=candidate_item_id,
        candidate_spec=_trunc(cand_spec, limit),
        conflicting_claim_id=conflicting_claim_id,
        conflicting_item_id=other_id,
        conflicting_item_spec=_trunc(other_spec, limit),
        conflicting_claim_state=claim["state"],
        shared_paths=list(shared_paths),
        shared_path_metadata=_shared_path_metadata(conn, shared_paths),
        suggested_commands=_suggested_commands(
            candidate_item_id, other_id, list(shared_paths),
            conflicting_claim_id,
        ),
        decision_options=list(DECISION_OPTIONS),
        rationale_checklist=list(_RATIONALE_CHECKLIST),
    )
