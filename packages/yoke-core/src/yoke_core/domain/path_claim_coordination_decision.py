"""Evidence-building helper for the LLM-agent coordination-only decision.

Gathers context an LLM agent needs to choose between ``coordination_only``,
directional ``activation``, or operator ``escalate`` for two overlapping
claims. Does NOT make the decision — semantic independence analysis is the
agent's job. The packet carries both specs, the conflicting claim's state,
shared-path metadata, and three ready-to-paste command lines (one per
decision option). The session holding the candidate's work claim records
the decision with its own skill as ``source``. When no live holder exists,
the pre-filled source is ``refine``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, TypedDict

from yoke_contracts.dependency_values import VALID_SOURCES
from yoke_core.domain import db_backend, runtime_settings
from yoke_core.domain.dependency_types import GatePoint, Satisfaction
from yoke_core.domain.items_queries import query_item
from yoke_core.domain.path_registry import ancestors_of, target_at
from yoke_core.domain.project_identity import render_item_ref
from yoke_contracts.public_ref import ITEM_NOT_FOUND


_DEFAULT_SPEC_TRUNCATION_BYTES = 4096
_TRUNCATION_CONFIG_KEY = "coordination_context_spec_truncation_bytes"
DECISION_OPTIONS: List[str] = ["coordination_only", "directional", "escalate"]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class HolderAttestation:
    """Who may record an overlap decision for one item."""

    holder_present: bool
    source: Optional[str]
    detail: str


def resolve_holder_attestation(conn: Any, item_id: int) -> HolderAttestation:
    """Return the live work-claim holder's dependency source.

    ``holder_present`` is false when no exclusive claim is visible, including
    when the claim tables are absent. A holder whose session mode is not a
    dependency source leaves ``source`` empty and names the mode in ``detail``.
    """
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "work_claims") or not _table_exists(
        conn, "harness_sessions"
    ):
        return HolderAttestation(False, None, "")
    from yoke_core.domain.work_claim_holder import holder_session_for_item

    holder = holder_session_for_item(conn, int(item_id))
    session_id = holder.get("holder_session_id")
    if not session_id:
        return HolderAttestation(False, None, "")
    row = conn.execute(
        f"SELECT mode FROM harness_sessions WHERE session_id = {_p(conn)}",
        (str(session_id),),
    ).fetchone()
    mode = str(row[0]).strip() if row and row[0] else ""
    if not mode:
        return HolderAttestation(
            True,
            None,
            "Work-claim holder session has no mode. Route the holder, "
            "shared paths and evidence via yoke say --steering.",
        )
    if mode not in VALID_SOURCES:
        return HolderAttestation(
            True,
            None,
            f"Work-claim holder session mode {mode!r} is not a dependency "
            "source. Route the holder, shared paths and evidence via "
            "yoke say --steering.",
        )
    return HolderAttestation(True, mode, "")


def dependency_source_for_commands(conn: Any, item_id: int) -> str:
    """Source token pasted into ``yoke items dependency add``.

    The live holder's skill when one exists, ``refine`` when nobody holds
    the work claim, and ``<source>`` when the holder cannot be named.
    """
    attestation = resolve_holder_attestation(conn, item_id)
    if attestation.source:
        return attestation.source
    if attestation.holder_present:
        return "<source>"
    return "refine"


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
            _TRUNCATION_CONFIG_KEY, _DEFAULT_SPEC_TRUNCATION_BYTES
        )
    except Exception:
        return _DEFAULT_SPEC_TRUNCATION_BYTES


def _read_spec(item_id: int) -> str:
    # query_item returns "" for missing rows AND present-but-NULL fields;
    # disambiguate by re-reading id (non-empty proves the row exists).
    spec = query_item(item_id, "spec")
    if spec != "":
        return spec
    if query_item(item_id, "id") == "":
        raise ValueError(ITEM_NOT_FOUND)
    return ""


def _conflicting_claim_row(conn: Any, claim_id: int) -> dict:
    row = conn.execute(
        "SELECT id, state, owner_item_id, integration_target FROM path_claims "
        "WHERE owner_kind = 'item' "
        f"AND id = {_p(conn)}",
        (claim_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"path_claim {claim_id} not found")
    return {
        "id": int(row["id"]),
        "state": str(row["state"]),
        "item_id": int(row["owner_item_id"]) if row["owner_item_id"] is not None else 0,
        "integration_target": str(row["integration_target"]),
    }


def _item_project_id(conn: Any, item_id: int) -> int:
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {_p(conn)}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise ValueError(ITEM_NOT_FOUND)
    return int(row["project_id"])


def _shared_path_metadata(
    conn: Any,
    project_id: int,
    shared_paths: List[str],
) -> List[dict]:
    """Path-registry facts for each shared path in the candidate's project."""
    out: List[dict] = []
    for path in shared_paths:
        target_id = target_at(conn, project_id, path)
        if target_id is None:
            out.append({"path": path, "kind": "unknown", "lineage_depth": 0})
            continue
        kind_row = conn.execute(
            f"SELECT kind FROM path_targets WHERE id = {_p(conn)}",
            (target_id,),
        ).fetchone()
        kind = str(kind_row["kind"]) if kind_row is not None else "unknown"
        out.append(
            {
                "path": path,
                "kind": kind,
                "lineage_depth": len(ancestors_of(conn, target_id)),
            }
        )
    return out


_RATIONALE_CHECKLIST: List[str] = [
    "decision=<coordination_only|directional|escalate>",
    "shared_paths=<comma-separated paths from the overlap>",
    "conflicting_claim_id=<the path_claims.id this row coordinates with>",
    "independence_evidence=<for coordination_only: which disjoint "
    "sections/functions each work item edits; explicitly absent for directional>",
    "why_order_matters=<for directional: what upstream lands that the "
    "candidate inherits or restructures; explicitly absent for coordination_only>",
]


def _suggested_commands(
    conn: Any,
    cand_id: int,
    other_id: int,
    shared_paths: List[str],
    conflicting_claim_id: int,
) -> List[str]:
    # Public refs, rendered from each item's own project — the pasted
    # command must name the item the operator sees, across projects too.
    cand = render_item_ref(conn, cand_id)
    other = render_item_ref(conn, other_id)
    co = GatePoint.COORDINATION_ONLY.value
    merged = Satisfaction.FACT_MERGED.value
    dep_add = "yoke items dependency add"
    source = dependency_source_for_commands(conn, cand_id)
    shared = ",".join(shared_paths) if shared_paths else "<shared-paths>"
    coord_rationale = (
        f"decision=coordination_only. shared_paths={shared}. "
        f"conflicting_claim_id={conflicting_claim_id}. "
        "independence_evidence=<which disjoint sections each work item edits>"
    )
    dir_rationale = (
        f"decision=directional. shared_paths={shared}. "
        f"conflicting_claim_id={conflicting_claim_id}. "
        "why_order_matters=<what upstream lands that the candidate inherits>"
    )
    return [
        "# option: coordination_only (independent same-file edits, "
        "path-claim mutex with no lifecycle gate)",
        f"{dep_add} {cand} {other} {source} --gate-point {co} "
        f'--rationale "{coord_rationale}"',
        "# option: directional activation (order-dependent edits, "
        "lifecycle gate + path-claim mutex)",
        f"{dep_add} {cand} {other} {source} --gate-point activation "
        f'--satisfaction {merged} --rationale "{dir_rationale}"',
        "# fact:merged is correct for trunk ordering; use "
        "fact:deployed:<environment-name> only when the dependent needs "
        "the blocker running in that registered environment",
        "# option: escalate (scope or authority decision)",
        f'yoke say --steering "Overlap decision needed for {cand}: '
        f"holder={other}; conflicting_claim_id={conflicting_claim_id}; "
        f'shared_paths={shared}; evidence=<why independence is uncertain>"',
    ]


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


def build_coordination_context(
    conn: Any,
    *,
    candidate_item_id: int,
    conflicting_claim_id: int,
    shared_paths: List[str],
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
        shared_path_metadata=_shared_path_metadata(
            conn,
            _item_project_id(conn, candidate_item_id),
            shared_paths,
        ),
        suggested_commands=_suggested_commands(
            conn,
            candidate_item_id,
            other_id,
            list(shared_paths),
            conflicting_claim_id,
        ),
        decision_options=list(DECISION_OPTIONS),
        rationale_checklist=list(_RATIONALE_CHECKLIST),
    )
