"""Pre-handoff readiness checks for idea / refine entry.

- ``verify_function_owners``: spec ``module.function`` refs resolve to
  real ``def``s.
- ``verify_file_budget_line_counts``: ``wc -l`` matches recorded counts
  (within ~5%); files >=330 lines need a sibling plan.
- ``verify_file_budget_claim_consistency``: File Budget paths and
  path-claim targets agree.
- ``run_all_checks``: composes them; CLI exits 0 on pass, 1 with
  structured remediation.

Idea calls before "next step: /yoke refine"; refine calls before
``idea → refining-idea``. Checks are read-only against spec text,
path-claim DB, and repo files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain.file_budget_paths import extract_file_budget_paths_set as _extract_file_budget_paths
from yoke_core.domain.attestation_rehearsal_dryrun import verify_attestation_rehearsal_commands
from yoke_core.domain import db_backend
from yoke_core.domain.idea_readiness_check_architecture import verify_architecture_impact_resolved
from yoke_core.domain.idea_readiness_check_rg import rg_available
from yoke_core.domain.idea_readiness_check_refs import (
    function_refs_to_verify as _function_refs_to_verify,
    is_module_or_planned_ref,
    module_file_candidates as _module_file_candidates,
)
from yoke_core.domain.idea_readiness_check_repo_root import _resolve_repo_root, _resolve_repo_root_for_item
from yoke_core.domain.idea_readiness_symlink_advisory import collect_symlink_advisories

LINE_CAP = 350
SIBLING_REQUIRED_THRESHOLD = 330


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass
class Issue:
    code: str
    message: str
    remediation: str
    context: dict = field(default_factory=dict)


def _strip_sun_prefix(item_ref: str) -> str:
    text = str(item_ref or "").strip()
    if text[:4].lower() == "yok-":
        text = text[4:]
    return text.lstrip("0") or "0"


def _read_spec_for_item(conn: Any, item_id: int) -> str:
    p = _p(conn)
    row = conn.execute(
        f"SELECT spec FROM items WHERE id = {p}", (item_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return ""
    return str(row[0])


def verify_function_owners(
    spec_text: str,
    conn: Optional[Any] = None,
    item_id: int = 0,
) -> List[Issue]:
    """Every ``runtime.api...func_name`` paired with a verb
    (modify/extend/edit/wraps/add behavior to) resolves to a real
    ``def func_name`` in the named module's .py file. Missing or
    renamed definitions surface as ``Issue``.
    """
    issues: List[Issue] = []
    # Pre-filter: skip package-submodule and planned refs before rg search.
    refs = {
        (fp, fn) for fp, fn in _function_refs_to_verify(spec_text)
        if not is_module_or_planned_ref(fp, item_id, conn)
    }
    if not refs or rg_available() is None:
        return issues
    repo_root = _resolve_repo_root_for_item(conn, item_id)
    for full_path, func_name in refs:
        module_path = full_path.rsplit(".", 1)[0]
        candidates = _module_file_candidates(repo_root, module_path)
        candidate = next((path for path in candidates if path.exists()), None)
        relative = str((candidate or candidates[0]).relative_to(repo_root))
        if candidate is None:
            issues.append(Issue(
                code="UNRESOLVED_MODULE",
                message=(
                    f"spec references {full_path} but {relative} does "
                    f"not exist"
                ),
                remediation=(
                    f"verify the module path; if the function lives "
                    f"elsewhere update the spec accordingly"
                ),
                context={"reference": full_path, "module_path": relative},
            ))
            continue
        proc = subprocess.run(
            ["rg", "-n", f"^def {func_name}\\b", str(candidate)],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            issues.append(Issue(
                code="UNRESOLVED_FUNCTION",
                message=(
                    f"spec references {full_path} but {relative} has "
                    f"no `def {func_name}`"
                ),
                remediation=(
                    f"grep `def {func_name}` across the repo to find "
                    f"the real definition and update the spec; or "
                    f"replace with a clarification question if the "
                    f"function is genuinely planned"
                ),
                context={"reference": full_path, "module_path": relative},
            ))
    return issues


def verify_file_budget_line_counts(
    spec_text: str,
    conn: Optional[Any] = None,
    item_id: int = 0,
) -> List[Issue]:
    """Each existing-file edit target named in File Budget must
    record the current ``wc -l`` (within ~5% tolerance), and any file
    >=330 lines must have a sibling-module plan in the spec.
    """
    issues: List[Issue] = []
    repo_root = _resolve_repo_root_for_item(conn, item_id)
    # Look for "path/to/file.py = N" patterns (from File Budget).
    pattern = re.compile(
        r"`?([\w/\.\-]+\.(?:py|md))`?\s*=\s*(\d+)"
    )
    for match in pattern.finditer(spec_text):
        rel = match.group(1)
        recorded = int(match.group(2))
        candidate = repo_root / rel
        if not candidate.exists():
            continue
        actual = sum(1 for _ in candidate.open(encoding="utf-8"))
        if actual != recorded:
            tolerance = max(2, int(recorded * 0.05))
            if abs(actual - recorded) > tolerance:
                issues.append(Issue(
                    code="STALE_LINE_COUNT",
                    message=(
                        f"spec records {rel}={recorded} lines but the "
                        f"file currently has {actual} lines"
                    ),
                    remediation=(
                        f"refresh the File Budget with the current "
                        f"`wc -l {rel}`"
                    ),
                    context={"path": rel, "recorded": recorded,
                             "actual": actual},
                ))
        if actual >= SIBLING_REQUIRED_THRESHOLD:
            sibling_pattern = re.compile(
                r"\bsibling\b|\bextract\b|\bnew sibling\b|\bsibling module\b",
                re.IGNORECASE,
            )
            if not sibling_pattern.search(spec_text):
                issues.append(Issue(
                    code="MISSING_SIBLING_PLAN",
                    message=(
                        f"{rel} is at {actual} lines (>= "
                        f"{SIBLING_REQUIRED_THRESHOLD}) but the spec "
                        f"has no sibling-module plan"
                    ),
                    remediation=(
                        f"declare an explicit sibling-module plan in "
                        f"the spec, e.g. "
                        f"`runtime/api/domain/<sibling>.py (new)`"
                    ),
                    context={"path": rel, "lines": actual},
                ))
    return issues


def verify_file_budget_claim_consistency(
    conn: Any, item_id: int,
) -> List[Issue]:
    """Confirm File Budget paths and path-claim targets agree."""
    spec_text = _read_spec_for_item(conn, item_id)
    if not spec_text:
        return []
    file_budget_paths = _extract_file_budget_paths(spec_text)
    claim_paths = _claim_declared_paths(conn, item_id)
    if not file_budget_paths and not claim_paths:
        return []
    in_budget_not_in_claim = file_budget_paths - claim_paths
    in_claim_not_in_budget = claim_paths - file_budget_paths
    issues: List[Issue] = []
    for path in sorted(in_budget_not_in_claim):
        issues.append(Issue(
            code="FILE_BUDGET_NOT_IN_CLAIM",
            message=(
                f"File Budget names {path} but the path-claim does not "
                f"declare it"
            ),
            remediation=(
                f"widen the claim to include {path} (or remove from "
                f"File Budget if the file is referenced as context, "
                f"not as an edit target)"
            ),
            context={"path": path},
        ))
    for path in sorted(in_claim_not_in_budget):
        issues.append(Issue(
            code="CLAIM_NOT_IN_FILE_BUDGET",
            message=(
                f"path-claim declares {path} but the File Budget does "
                f"not name it"
            ),
            remediation=(
                f"add {path} to the File Budget (or narrow the claim "
                f"if the file is no longer touched)"
            ),
            context={"path": path},
        ))
    return issues


def run_all_checks(
    conn: Any, item_id: int,
) -> List[Issue]:
    """Compose the readiness checks; returns the union of issues."""
    from yoke_core.domain.idea_readiness_repair_cross_item_overlap import (
        probe_cross_item_overlap,
    )
    spec_text = _read_spec_for_item(conn, item_id)
    issues: List[Issue] = []
    issues.extend(verify_function_owners(spec_text, conn, item_id))
    issues.extend(verify_file_budget_line_counts(spec_text, conn, item_id))
    issues.extend(verify_file_budget_claim_consistency(conn, item_id))
    issues.extend(verify_architecture_impact_resolved(conn, item_id))
    issues.extend(verify_attestation_rehearsal_commands(conn, item_id))
    issues.extend(probe_cross_item_overlap(conn, item_id))
    return issues


def run_all_advisories(
    conn: Any, item_id: int,
) -> List[dict]:
    """Compose non-blocking readiness advisories."""
    spec_text = _read_spec_for_item(conn, item_id)
    if not spec_text:
        return []
    return collect_symlink_advisories(
        spec_text,
        repo_root=_resolve_repo_root_for_item(conn, item_id),
    )


def _claim_declared_paths(
    conn: Any, item_id: int,
) -> set:
    p = _p(conn)
    try:
        rows = conn.execute(
            "SELECT pt.path_string FROM path_claim_targets pct "
            "JOIN path_claims pc ON pc.id = pct.claim_id "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            f"WHERE pc.item_id = {p} AND pc.state IN "
            "('planned', 'blocked', 'active') AND pt.kind = 'file'",
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return set()
    return {str(r[0]) for r in rows}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.idea_readiness_check",
        description=(
            "Pre-handoff readiness check for idea / refine entry. "
            "Exits 0 when all checks pass, 1 when any issue is found."
        ),
    )
    parser.add_argument("item", help="YOK-N or N")
    parser.add_argument(
        "--skip-readiness-check", action="store_true", default=False,
        help=(
            "Operator override: record a skip in the audit trail and "
            "exit 0. Allowed at idea-time (advisory); refine-entry "
            "ignores this flag and re-runs the checks."
        ),
    )
    args = parser.parse_args(argv)
    item_id = int(_strip_sun_prefix(args.item))
    if args.skip_readiness_check:
        print(json.dumps({
            "verdict": "skipped",
            "issues": [],
            "skip_reason": "operator-override",
        }))
        return 0
    from yoke_core.domain.schema_common import (
        _connect_raw, _resolve_db_path,
    )
    conn = _connect_raw(_resolve_db_path())
    try:
        issues = run_all_checks(conn, item_id)
        advisories = run_all_advisories(conn, item_id)
    finally:
        conn.close()
    issue_dicts = [
        {"code": i.code, "message": i.message,
         "remediation": i.remediation, "context": i.context}
        for i in issues
    ]
    # Classification inline so agents read it via stdlib json — the
    # agent-CLI contract lint blocks `python3 -c "from runtime..."`.
    from yoke_core.domain.idea_readiness_repair import classify_readiness_issues
    payload = {
        "verdict": "pass" if not issues else "block",
        "classification": classify_readiness_issues(issue_dicts),
        "issues": issue_dicts,
        "advisories": advisories,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not issues else 1


__all__ = [
    "Issue",
    "main",
    "run_all_advisories",
    "run_all_checks",
    "verify_attestation_rehearsal_commands",
    "verify_file_budget_claim_consistency",
    "verify_file_budget_line_counts",
    "verify_function_owners",
]


if __name__ == "__main__":
    raise SystemExit(main())
