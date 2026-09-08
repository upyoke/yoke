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
empty/shrinkage refusals, and post-repair counts >=
``SIBLING_REQUIRED_THRESHOLD`` (330) without a sibling-module plan in the
spec.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.backlog_structured_write_op import execute_structured_write
from yoke_core.domain.idea_readiness_file_budget_sizing import (
    SIBLING_REQUIRED_THRESHOLD,
)
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

_SIBLING_PATTERN = re.compile(
    r"\bsibling\b|\bextract\b|\bnew sibling\b|\bsibling module\b",
    re.IGNORECASE,
)
# Repair re-reads live line counts off disk, so a host with no checkout for
# the item's project has nothing to repair against.
_NO_CHECKOUT_ERROR = (
    "no checkout for this item's project on this host; repair reads live "
    "line counts from the project's files. Re-run from a machine whose "
    "checkout for that project is registered."
)


@dataclass(frozen=True)
class RepairedPath:
    path: str
    recorded: int
    actual: int


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
            "success": self.success, "classification": self.classification,
            "item_id": self.item_id,
            "repaired_paths": [asdict(p) for p in self.repaired_paths],
        }
        for k in ("refused_paths", "field_written", "rerun_verdict",
                  "rerun_issues", "error"):
            if getattr(self, k):
                out[k] = getattr(self, k)
        if self.audit_emitted:
            out["audit_emitted"] = True
        return out


def _path_pattern(path: str) -> re.Pattern:
    from yoke_core.domain.file_budget_sizing import path_sizing_pattern

    return path_sizing_pattern(path)


def apply_stale_count_replacements(
    spec_text: str, repairs: List[RepairedPath],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Apply each repair's new count; refuse missing or duplicate matches."""
    refused: List[Dict[str, Any]] = []
    text = spec_text or ""
    for r in repairs:
        pattern = _path_pattern(r.path)
        matches = list(pattern.finditer(text))
        if not matches:
            refused.append({"path": r.path, "reason": "missing_file_budget_entry",
                            "recorded": r.recorded, "actual": r.actual})
            continue
        if len(matches) > 1:
            refused.append({"path": r.path, "reason": "duplicate_count_match",
                            "recorded": r.recorded, "actual": r.actual,
                            "match_count": len(matches)})
            continue
        from yoke_core.domain.file_budget_sizing import replacement_for_current_size

        text = pattern.sub(
            lambda match, count=r.actual: replacement_for_current_size(
                match, count,
            ),
            text, count=1,
        )
    return text, refused


def _read_spec(item_id: int) -> Optional[str]:
    from yoke_core.domain.backlog_queries import (
        _query_item_field, _resolve_write_db_path,
    )
    from yoke_core.domain.db_helpers import connect

    conn = connect(_resolve_write_db_path())
    try:
        return _query_item_field(conn, item_id, "spec")
    finally:
        conn.close()


def _file_line_count(repo_root: Path, rel: str) -> Optional[int]:
    candidate = repo_root / rel
    if not candidate.exists():
        return None
    return sum(1 for _ in candidate.open(encoding="utf-8"))


def _emit_audit(*, item_id: int, repaired: List[RepairedPath],
                refused: List[Dict[str, Any]], rerun_verdict: str) -> bool:
    """Emit ``IdeaReadinessAutofixApplied`` (best-effort)."""
    try:
        from yoke_core.domain.events import emit_event

        result = emit_event(
            "IdeaReadinessAutofixApplied",
            event_kind="lifecycle", event_type="readiness_repair",
            source_type="backend", severity="INFO", outcome="completed",
            item_id=str(item_id),
            context={"field": "spec", "rerun_verdict": rerun_verdict,
                     "repaired_paths": [asdict(p) for p in repaired],
                     "refused_paths": refused},
        )
        return bool(getattr(result, "wrote", False) or getattr(result, "event_id", ""))
    except Exception:
        return False


def _resolve_repairs(
    issues: List[Dict[str, Any]], root: Path, spec_text: str,
) -> Tuple[List[RepairedPath], List[Dict[str, Any]]]:
    repairs: List[RepairedPath] = []
    refused: List[Dict[str, Any]] = []
    for issue in issues:
        ctx = issue.get("context") or {}
        path = str(ctx.get("path") or "")
        recorded_raw = ctx.get("recorded")
        if not path or recorded_raw is None:
            refused.append({"reason": "missing_context", "issue": issue})
            continue
        try:
            recorded = int(recorded_raw)
        except (TypeError, ValueError):
            refused.append({"reason": "non_integer_recorded", "path": path})
            continue
        actual = _file_line_count(root, path)
        if actual is None:
            refused.append({"path": path, "reason": "missing_file",
                            "recorded": recorded})
            continue
        if actual >= SIBLING_REQUIRED_THRESHOLD and not _SIBLING_PATTERN.search(spec_text):
            refused.append({"path": path, "reason": "missing_sibling_plan",
                            "recorded": recorded, "actual": actual})
            continue
        repairs.append(RepairedPath(path=path, recorded=recorded, actual=actual))
    return repairs, refused


def attempt_stale_count_repair(
    *, item_id: int, issues: List[Dict[str, Any]],
    repo_root: Optional[Path] = None,
) -> RepairOutcome:
    """Repair pure-stale-count readiness drift for ``item_id``.

    Caller MUST classify ``issues`` with :func:`classify_readiness_issues`
    first; helper re-checks and refuses anything other than pure-stale-count.
    """
    classification = classify_readiness_issues(issues)
    base = {"classification": classification, "item_id": item_id}
    if classification != CLASS_PURE_STALE_COUNT:
        return RepairOutcome(success=False, **base, error=(
            f"only pure stale-count handled; got classification={classification!r}"
        ))
    root = repo_root or _item_checkout(item_id)
    if root is None:
        return RepairOutcome(success=False, **base, error=_NO_CHECKOUT_ERROR)
    spec_text = _read_spec(item_id) or ""
    if not spec_text.strip():
        return RepairOutcome(success=False, **base,
                             error="spec field is empty; nothing to repair")
    repairs, refused = _resolve_repairs(issues, root, spec_text)
    if refused:
        return RepairOutcome(success=False, **base, refused_paths=refused,
                             error="ambiguous or unsafe repairs refused before write")
    if not repairs:
        return RepairOutcome(success=False, **base,
                             error="no repairable stale-count issues found")
    updated_text, write_refusals = apply_stale_count_replacements(spec_text, repairs)
    if write_refusals:
        return RepairOutcome(success=False, **base, refused_paths=write_refusals,
                             error="targeted spec replacement could not be applied")
    if updated_text == spec_text:
        return RepairOutcome(success=False, **base,
                             error="repair would be a no-op; refusing redundant write")
    write_result = execute_structured_write(
        item_id=item_id, field="spec", content=updated_text,
        source="readiness-autofix", out=_NullSink(),
    )
    if not write_result.get("success"):
        return RepairOutcome(success=False, **base, error=str(
            write_result.get("error") or "structured write failed"
        ))
    rerun = _rerun_readiness(item_id)
    rerun_verdict = rerun.verdict
    audit_emitted = _emit_audit(item_id=item_id, repaired=repairs,
                                refused=refused, rerun_verdict=rerun_verdict)
    return RepairOutcome(
        success=(rerun_verdict == VERDICT_PASS), **base,
        repaired_paths=repairs, field_written="spec",
        rerun_verdict=rerun_verdict, rerun_issues=rerun.issue_payloads(),
        audit_emitted=audit_emitted,
    )


def _item_checkout(item_id: int) -> Optional[Path]:
    """This machine's checkout for the item's project, or ``None``."""
    from yoke_core.domain.schema_common import _connect_raw, _resolve_db_path

    conn = _connect_raw(_resolve_db_path())
    try:
        return item_project_checkout(conn, item_id)
    finally:
        conn.close()


def _rerun_readiness(item_id: int) -> "ReadinessOutcome":
    from yoke_core.domain.idea_readiness_check import run_all_checks
    from yoke_core.domain.schema_common import _connect_raw, _resolve_db_path

    conn = _connect_raw(_resolve_db_path())
    try:
        return run_all_checks(conn, item_id)
    finally:
        conn.close()


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
            "blocks. Exits 0 when the post-repair verdict is pass."
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
        print(json.dumps({"success": True, "classification": CLASS_PASS,
                          "item_id": item_id, "rerun_verdict": verdict}))
        return 0
    if classification != CLASS_PURE_STALE_COUNT:
        print(json.dumps({
            "success": False, "classification": classification,
            "item_id": item_id, "rerun_verdict": verdict, "rerun_issues": issues,
            "error": (
                "only pure stale-count handled; refine must dispatch to its "
                "own branches for other codes"
            ),
        }))
        return 1
    outcome = attempt_stale_count_repair(item_id=item_id, issues=issues)
    print(json.dumps(outcome.to_payload(), sort_keys=True))
    return 0 if outcome.success else 1


attempt_claim_coverage_repair: Any

__all__ = [
    "CLASS_MIXED_STALE_COUNT", "CLASS_PASS", "CLASS_PURE_STALE_COUNT",
    "CLASS_UNAVAILABLE", "CLASS_UNRECOVERABLE", "RepairOutcome", "RepairedPath",
    "apply_stale_count_replacements", "attempt_claim_coverage_repair",
    "attempt_stale_count_repair", "classify_readiness_issues", "main",
]

def __getattr__(name):
    """Lazy re-export of attempt_claim_coverage_repair (avoids circular import)."""
    if name == "attempt_claim_coverage_repair":
        from yoke_core.domain.idea_readiness_repair_claim_coverage import attempt_claim_coverage_repair as _impl
        return _impl
    raise AttributeError(name)


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
