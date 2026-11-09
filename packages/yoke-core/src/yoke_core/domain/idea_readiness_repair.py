"""Stale-count auto-repair for refine-entry readiness checks.

``idea_readiness_check`` emits ``STALE_LINE_COUNT`` when the spec's File
Budget records a count that drifted from the live file. This helper turns
mechanical, evidence-bound drift into self-repair: re-read each named
path's live count, replace only the recorded number in the structured
``spec`` field via the canonical guarded write path, and re-run the check.

Mechanical only — never adds/removes File Budget paths, never rewrites
unrelated prose, never touches path claims; claim repair belongs to the
refine readiness path. Refuses ambiguous repairs: missing files, missing
File Budget entries, duplicate count matches, structured-write
empty/shrinkage refusals. Readiness findings never gate count refresh;
the rerun reports them separately from repair success.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_core.domain.idea_readiness_count_replacements import (
    RepairedPath,
    apply_stale_count_replacements,
    resolve_repairs,
)
from yoke_core.domain.backlog_structured_write_op import execute_structured_write
from yoke_core.domain.idea_readiness_checkout import item_project_checkout
from yoke_core.domain.idea_readiness_results import (
    CLASS_MIXED_STALE_COUNT,
    CLASS_PASS,
    CLASS_PURE_STALE_COUNT,
    CLASS_UNAVAILABLE,
    CLASS_UNRECOVERABLE,
    VERDICT_PASS,
    ReadinessOutcome,
    classify_readiness_issues,
)


@dataclass
class RepairOutcome:
    """Structured evidence returned by :func:`attempt_stale_count_repair`."""

    success: bool
    classification: str
    item_id: int = 0
    repaired_paths: List[RepairedPath] = field(default_factory=list)
    refused_paths: List[Dict[str, Any]] = field(default_factory=list)
    field_written: str = ""
    rerun_verdict: str = ""
    rerun_issues: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    audit_emitted: bool = False

    def to_payload(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "success": self.success,
            "classification": self.classification,
            "item_id": self.item_id,
            "repaired_paths": [asdict(p) for p in self.repaired_paths],
        }
        for k in (
            "refused_paths",
            "field_written",
            "rerun_verdict",
            "rerun_issues",
            "error",
        ):
            if getattr(self, k):
                out[k] = getattr(self, k)
        if self.audit_emitted:
            out["audit_emitted"] = True
        return out


def _read_spec(item_id: int) -> Optional[str]:
    from yoke_core.domain.backlog_queries import (
        _query_item_field,
        _resolve_write_db_path,
    )
    from yoke_core.domain.db_helpers import connect

    conn = connect(_resolve_write_db_path())
    try:
        return _query_item_field(conn, item_id, "spec")
    finally:
        conn.close()


def _emit_audit(
    *,
    item_id: int,
    repaired: List[RepairedPath],
    refused: List[Dict[str, Any]],
    rerun_verdict: str,
) -> bool:
    """Emit ``IdeaReadinessAutofixApplied`` (best-effort)."""
    try:
        from yoke_core.domain.events import emit_event

        result = emit_event(
            "IdeaReadinessAutofixApplied",
            event_kind="lifecycle",
            event_type="readiness_repair",
            source_type="backend",
            severity="INFO",
            outcome="completed",
            item_id=str(item_id),
            context={
                "field": "spec",
                "rerun_verdict": rerun_verdict,
                "repaired_paths": [asdict(p) for p in repaired],
                "refused_paths": refused,
            },
        )
        return bool(getattr(result, "wrote", False) or getattr(result, "event_id", ""))
    except Exception:
        return False


def attempt_stale_count_repair(
    *,
    item_id: int,
    issues: List[Dict[str, Any]],
    repo_root: Optional[Path] = None,
    observations: Optional[Dict[str, Any]] = None,
) -> RepairOutcome:
    """Refresh stale counts independently of other readiness findings.

    A host without the item project's checkout repairs from ``issues``
    that a machine holding it reported, and the re-run that proves the
    result goes back through the same handoff.
    """
    from yoke_core.domain.idea_readiness_repair_handoff import (
        NO_CHECKOUT_TO_REPAIR_AGAINST,
        repair_verifiable,
    )

    classification = classify_readiness_issues(issues)
    base = {"classification": classification, "item_id": item_id}
    stale_issues = [
        issue for issue in issues if issue.get("code") == "STALE_LINE_COUNT"
    ]
    if not stale_issues:
        return RepairOutcome(
            success=False,
            **base,
            error=("no stale counts to refresh; resolve rerun_issues through refine"),
            rerun_issues=issues,
        )
    root = repo_root or _item_checkout(item_id)
    if not repair_verifiable(root, observations):
        return RepairOutcome(
            success=False,
            **base,
            error=NO_CHECKOUT_TO_REPAIR_AGAINST,
        )
    spec_text = _read_spec(item_id) or ""
    if not spec_text.strip():
        return RepairOutcome(
            success=False, **base, error="spec field is empty; nothing to repair"
        )
    repairs, refused = resolve_repairs(stale_issues, root)
    if refused:
        return RepairOutcome(
            success=False,
            **base,
            refused_paths=refused,
            error="ambiguous or unsafe repairs refused before write",
        )
    if not repairs:
        return RepairOutcome(
            success=False, **base, error="no repairable stale-count issues found"
        )
    updated_text, write_refusals = apply_stale_count_replacements(spec_text, repairs)
    if write_refusals:
        return RepairOutcome(
            success=False,
            **base,
            refused_paths=write_refusals,
            error="targeted spec replacement could not be applied",
        )
    if updated_text == spec_text:
        return RepairOutcome(
            success=False,
            **base,
            error="repair would be a no-op; refusing redundant write",
        )
    write_result = execute_structured_write(
        item_id=item_id,
        field="spec",
        content=updated_text,
        source="readiness-autofix",
        out=_NullSink(),
    )
    if not write_result.get("success"):
        return RepairOutcome(
            success=False,
            **base,
            error=str(write_result.get("error") or "structured write failed"),
        )
    # Deliberately without the answer that drove this repair: the write
    # above changed the spec, so that answer is now bound to a revision
    # the control plane no longer holds. The re-run comes back
    # unperformed on a host without the tree, and the caller is asked for
    # a fresh reading rather than handed a verdict nothing verified.
    rerun = _rerun_readiness(item_id)
    rerun_verdict = rerun.verdict
    audit_emitted = _emit_audit(
        item_id=item_id, repaired=repairs, refused=refused, rerun_verdict=rerun_verdict
    )
    return RepairOutcome(
        success=True,
        **base,
        repaired_paths=repairs,
        field_written="spec",
        rerun_verdict=rerun_verdict,
        rerun_issues=rerun.issue_payloads(),
        audit_emitted=audit_emitted,
    )


def _item_checkout(item_id: int) -> Optional[Path]:
    """This machine's checkout for the item's project, or ``None``."""
    from yoke_core.domain.db_backend import connect
    from yoke_core.domain.schema_common import _resolve_db_path

    conn = connect(_resolve_db_path())
    try:
        return item_project_checkout(conn, item_id)
    finally:
        conn.close()


def _rerun_readiness(item_id: int) -> "ReadinessOutcome":
    from yoke_core.domain.idea_readiness_repair_handoff import rerun_readiness

    return rerun_readiness(item_id)


class _NullSink:
    def write(self, _data: str) -> int:  # pragma: no cover - trivial
        return 0

    def flush(self) -> None:  # pragma: no cover - trivial
        return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.idea_readiness_repair",
        description=(
            "Auto-repair stale File Budget line counts before refine "
            "blocks. Exits 0 when counts refresh; readiness is reported separately."
        ),
    )
    parser.add_argument("--item", required=True, help="YOK-N or N")
    args = parser.parse_args(argv)
    try:
        from yoke_core.domain.yok_n_parser import parse_item_argument

        item_id = parse_item_argument(args.item)
    except ValueError as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        return 1
    outcome = _rerun_readiness(item_id)
    verdict = outcome.verdict
    issues = outcome.issue_payloads()
    classification = outcome.classification
    if verdict == VERDICT_PASS:
        print(
            json.dumps(
                {
                    "success": True,
                    "classification": CLASS_PASS,
                    "item_id": item_id,
                    "rerun_verdict": verdict,
                }
            )
        )
        return 0
    if not any(issue.get("code") == "STALE_LINE_COUNT" for issue in issues):
        print(
            json.dumps(
                {
                    "success": False,
                    "classification": classification,
                    "item_id": item_id,
                    "rerun_verdict": verdict,
                    "rerun_issues": issues,
                    "error": (
                        "no stale counts to refresh; resolve rerun_issues through refine"
                    ),
                }
            )
        )
        return 1
    outcome = attempt_stale_count_repair(item_id=item_id, issues=issues)
    print(json.dumps(outcome.to_payload(), sort_keys=True))
    return 0 if outcome.success else 1


attempt_claim_coverage_repair: Any

__all__ = [
    "CLASS_MIXED_STALE_COUNT",
    "CLASS_PASS",
    "CLASS_PURE_STALE_COUNT",
    "CLASS_UNAVAILABLE",
    "CLASS_UNRECOVERABLE",
    "RepairOutcome",
    "RepairedPath",
    "apply_stale_count_replacements",
    "attempt_claim_coverage_repair",
    "attempt_stale_count_repair",
    "classify_readiness_issues",
    "main",
]


def __getattr__(name):
    """Lazy re-export of attempt_claim_coverage_repair (avoids circular import)."""
    if name == "attempt_claim_coverage_repair":
        from yoke_core.domain.idea_readiness_repair_claim_coverage import (
            attempt_claim_coverage_repair as _impl,
        )

        return _impl
    raise AttributeError(name)


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
