"""Cross-item path-claim overlap probe for refine readiness.

Surfaces refined-idea-blocking overlap as a readiness ``Issue`` at
refine entry so the agent classifies the cluster
(``coordination_only`` / directional ``activation`` / escalate) before
promotion. Without this gate the unresolved overlap ambushes the next
phase that runs activation.

The probe walks the candidate's non-terminal path-claims
(``planned``/``blocked``/``active``) and looks for non-terminal claims
owned by other items that share at least one declared ``target_id`` on
the same ``integration_target``. It mirrors register-phase semantics:
planned siblings count (unlike ``classify_overlap(phase='activate')``).
For each cluster, the probe consults the directional dep-graph
classifier and the override surface — authored ``coordination_only``
edges, ``HAS_SERIAL`` dependencies, the reverse upstream-of-``blocks``
case, and active overrides all silence the cluster. Only truly
``NO_EDGE`` clusters surface a ``cross_item_overlap`` ``Issue``.

The default repair path is evidence-returning and non-mutating: the
helper returns ``CoordinationContext`` packets plus suggested commands,
and the agent calls ``yoke shepherd dependency-add ... --gate-point ...``
itself per ``AGENTS.md`` ``## Path Claims — Hard Rule``. ``auto_attest``
is reserved for future workflows that have already proven independence
via ``classify_inter_item_edges``.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.idea_readiness_check import Issue, _strip_sun_prefix
from yoke_core.domain.path_claim_coordination_decision import (
    build_coordination_context,
)
from yoke_core.domain.path_claims_dependency_resolver_coordination import (
    CoordinationClassification,
    classify_inter_item_edges,
    has_forward_serial_edge,
)
from yoke_core.domain.path_claims_override import is_active_override


ISSUE_CODE = "cross_item_overlap"
_CLASSIFIER_PHASE = "register"
_NON_TERMINAL = ("planned", "blocked", "active")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class OverlapCluster:
    """One unresolved INCOMPATIBLE cross-item cluster."""

    candidate_item_id: int
    candidate_claim_id: int
    conflicting_claim_id: int
    conflicting_item_id: int
    integration_target: str
    shared_paths: Tuple[str, ...]


@dataclass
class CrossItemRepairResult:
    """Evidence packet returned by :func:`attempt_cross_item_overlap_repair`."""

    success: bool
    item_id: int
    auto_attest: bool
    clusters: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def to_payload(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "success": self.success, "item_id": self.item_id,
            "auto_attest": self.auto_attest, "clusters": self.clusters,
        }
        if self.error:
            out["error"] = self.error
        return out


def probe_cross_item_overlap(
    conn: Any, item_id: int,
) -> List[Issue]:
    """Return one ``Issue`` per unresolved cross-item INCOMPATIBLE cluster."""
    clusters = _find_unresolved_clusters(conn, item_id=int(item_id))
    return [_cluster_to_issue(c) for c in clusters]


def attempt_cross_item_overlap_repair(
    conn: Any, *, item_id: int, auto_attest: bool = False,
) -> CrossItemRepairResult:
    """Return the evidence packet the agent needs to author the edge.

    Default (``auto_attest=False``) is read-only: build a
    ``CoordinationContext`` per cluster and return them. ``auto_attest``
    is reserved for future workflows — the decision is agent-attested
    per ``AGENTS.md ## Path Claims — Hard Rule``.
    """
    if auto_attest:
        return CrossItemRepairResult(
            success=False, item_id=int(item_id), auto_attest=True,
            error="auto_attest=True is reserved for future workflows",
        )
    clusters = _find_unresolved_clusters(conn, item_id=int(item_id))
    if not clusters:
        return CrossItemRepairResult(
            success=True, item_id=int(item_id), auto_attest=False,
        )
    packets: List[Dict[str, Any]] = []
    for cluster in clusters:
        ctx = build_coordination_context(
            conn, candidate_item_id=cluster.candidate_item_id,
            conflicting_claim_id=cluster.conflicting_claim_id,
            shared_paths=list(cluster.shared_paths),
        )
        packets.append({
            "candidate_claim_id": cluster.candidate_claim_id,
            "conflicting_claim_id": cluster.conflicting_claim_id,
            "conflicting_item_id": cluster.conflicting_item_id,
            "integration_target": cluster.integration_target,
            "shared_paths": list(cluster.shared_paths),
            "coordination_context": ctx,
        })
    return CrossItemRepairResult(
        success=False, item_id=int(item_id), auto_attest=False,
        clusters=packets,
    )


_OVERLAP_SQL = """
SELECT pc_cand.id AS cand_claim_id, pc_other.id AS other_claim_id,
       pc_other.item_id AS other_item_id,
       pc_cand.integration_target AS itarget, pt.path_string AS path
  FROM path_claims pc_cand
  JOIN path_claim_targets pct_cand ON pct_cand.claim_id = pc_cand.id
  JOIN path_targets pt ON pt.id = pct_cand.target_id
  JOIN path_claim_targets pct_other ON pct_other.target_id = pct_cand.target_id
  JOIN path_claims pc_other ON pc_other.id = pct_other.claim_id
 WHERE pc_cand.item_id = {p} AND pc_cand.state IN ({states})
   AND pc_other.id <> pc_cand.id AND pc_other.state IN ({states})
   AND pc_other.integration_target = pc_cand.integration_target
   AND pc_other.mode <> 'exception'
   AND (pc_other.item_id IS NULL OR pc_other.item_id <> pc_cand.item_id)
"""


def _find_unresolved_clusters(
    conn: Any, *, item_id: int,
) -> List[OverlapCluster]:
    """Walk the SQL surface; apply directional + override filters."""
    p = _p(conn)
    states = ",".join(p for _ in _NON_TERMINAL)
    try:
        rows = conn.execute(
            _OVERLAP_SQL.format(p=p, states=states),
            (item_id, *_NON_TERMINAL, *_NON_TERMINAL),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except db_backend.database_error_types(conn):
            pass
        return []

    buckets: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for row in rows:
        other_item_raw = _row_get(row, "other_item_id", 2)
        if other_item_raw is None:
            continue  # other claim is project-only, not item-scoped
        key = (
            int(_row_get(row, "cand_claim_id", 0)),
            int(_row_get(row, "other_claim_id", 1)),
        )
        bucket = buckets.setdefault(key, {
            "candidate_claim_id": int(_row_get(row, "cand_claim_id", 0)),
            "conflicting_claim_id": int(_row_get(row, "other_claim_id", 1)),
            "conflicting_item_id": int(other_item_raw),
            "integration_target": str(_row_get(row, "itarget", 3)),
            "shared_paths": set(),
        })
        bucket["shared_paths"].add(str(_row_get(row, "path", 4)))

    out: List[OverlapCluster] = []
    for bucket in buckets.values():
        if _cluster_is_attested(conn, bucket, item_id=item_id):
            continue
        out.append(OverlapCluster(
            candidate_item_id=item_id,
            candidate_claim_id=bucket["candidate_claim_id"],
            conflicting_claim_id=bucket["conflicting_claim_id"],
            conflicting_item_id=bucket["conflicting_item_id"],
            integration_target=bucket["integration_target"],
            shared_paths=tuple(sorted(bucket["shared_paths"])),
        ))
    return out


def _cluster_is_attested(
    conn: Any, bucket: Dict[str, Any], *, item_id: int,
) -> bool:
    """True when an authored row or override silences the cluster."""
    other_claim = bucket["conflicting_claim_id"]
    other_item = bucket["conflicting_item_id"]
    if is_active_override(
        conn, path_claim_id=bucket["candidate_claim_id"],
        blocking_claim_id=other_claim,
    ):
        return True
    edge = classify_inter_item_edges(
        conn, candidate_claim_id=bucket["candidate_claim_id"],
        candidate_item_id=item_id, blocking_claim_id=other_claim,
    )
    if edge in (CoordinationClassification.COORDINATION_ONLY,
                CoordinationClassification.HAS_SERIAL):
        return True
    # NO_EDGE disambiguation: candidate-as-BLOCKER of a non-coord edge
    # is attested upstream and silences the cluster; truly missing rows
    # surface as the readiness issue.
    return has_forward_serial_edge(
        conn, dependent_item_id=other_item, blocking_item_id=item_id,
    )


def _row_get(row: Any, key: str, index: int) -> Any:
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    return row[index]


def _cluster_to_issue(cluster: OverlapCluster) -> Issue:
    paths = list(cluster.shared_paths)
    shared_join = ",".join(paths) if paths else "<shared-paths>"
    recovery_command = (
        "yoke claims path coordination-decision-build "
        f"--item YOK-{cluster.candidate_item_id} "
        f"--conflicting-claim {cluster.conflicting_claim_id} "
        f"--paths {shared_join}"
    )
    return Issue(
        code=ISSUE_CODE,
        message=(
            f"path-claim overlap on {len(paths)} shared path(s) with "
            f"YOK-{cluster.conflicting_item_id} "
            f"(claim_id={cluster.conflicting_claim_id}) is unresolved"
        ),
        remediation=(
            f"classify the overlap with {recovery_command} and author "
            f"the matching item_dependencies row via "
            f"`yoke shepherd dependency-add YOK-{cluster.candidate_item_id} "
            f"YOK-{cluster.conflicting_item_id} refine --gate-point "
            f"coordination_only|activation --rationale '...'`"
        ),
        context={
            "candidate_item_id": cluster.candidate_item_id,
            "candidate_claim_id": cluster.candidate_claim_id,
            "conflicting_claim_id": cluster.conflicting_claim_id,
            "conflicting_item_id": cluster.conflicting_item_id,
            "integration_target": cluster.integration_target,
            "shared_paths": paths,
            "classifier_phase": _CLASSIFIER_PHASE,
            "recovery_command": recovery_command,
        },
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke_core.domain.idea_readiness_repair_cross_item_overlap",
        description=("Probe cross-item path-claim overlap. Exits 0 when "
                     "no cluster is open, 1 otherwise."),
    )
    parser.add_argument("--item", required=True, help="YOK-N or N")
    parser.add_argument(
        "--evidence", action="store_true",
        help="Return the coordination-decision evidence packet per cluster.",
    )
    args = parser.parse_args(argv)
    try:
        item_id = int(_strip_sun_prefix(args.item))
    except ValueError:
        print(json.dumps({"success": False,
                          "error": f"invalid item: {args.item!r}"}))
        return 1
    from yoke_core.domain.schema_common import _connect_raw, _resolve_db_path
    conn = _connect_raw(_resolve_db_path())
    try:
        if args.evidence:
            outcome = attempt_cross_item_overlap_repair(conn, item_id=item_id)
            print(json.dumps(outcome.to_payload(), sort_keys=True, indent=2))
            return 0 if outcome.success else 1
        issues = probe_cross_item_overlap(conn, item_id=item_id)
    finally:
        conn.close()
    print(json.dumps({
        "verdict": "pass" if not issues else "block",
        "issues": [{"code": i.code, "message": i.message,
                    "remediation": i.remediation, "context": i.context}
                   for i in issues],
    }, indent=2))
    return 0 if not issues else 1


__all__ = [
    "CrossItemRepairResult",
    "ISSUE_CODE",
    "OverlapCluster",
    "attempt_cross_item_overlap_repair",
    "main",
    "probe_cross_item_overlap",
]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
