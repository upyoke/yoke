"""Backlog-to-GitHub resync engine public facade."""

from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain import backlog_github_sync, epic_task_sync  # noqa: F401
from yoke_core.domain.epic import task_update_field  # noqa: F401
from yoke_core.domain.worktree import (  # noqa: F401
    resolve_yoke_root as resolve_worktree_yoke_root,
)
from yoke_core.domain.project_github_auth import (  # noqa: F401
    InvalidToken,
    MissingCapability,
    MissingRepoMetadata,
    MissingToken,
    ProjectGithubAuth,
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.engines.resync_runtime import (  # noqa: F401
    _resolve_yoke_root,
    _is_dry_run,
    _gh_env,
    _query_item_status,
    _call_domain_sync,
)
from yoke_core.engines.resync_detect import (  # noqa: F401
    PairedItem,
    DriftRecord,
    _trim_trailing,
    normalize_body_for_compare,
    _get_label_value,
    stage2_compare,
)
from yoke_core.engines.resync_detect_fetch import (  # noqa: F401
    SYNC_DISABLED_KEY,
    _project_sync_disabled,
)
from yoke_core.engines.resync_apply import (  # noqa: F401
    _emit_doctor_format,
)
from yoke_core.engines.resync_wrappers import (  # noqa: F401
    _fetch_gh_issues_per_project,
    _graphql_batch_fetch,
    stage1_linkage,
    stage1_5_heavy_fetch,
    _repair_local_orphan_backlog,
    _repair_local_orphan_epic_task,
    _repair_drift,
)

def main(argv: Optional[List[str]] = None) -> int:
    """Run the resync engine. Returns exit code."""
    args = argv if argv is not None else sys.argv[1:]

    # Parse arguments
    mode = "detect"
    doctor_format = False
    db_path = ""

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--detect-only":
            mode = "detect"
        elif arg == "--fix":
            mode = "fix"
        elif arg == "--doctor-format":
            doctor_format = True
        elif arg == "--db-path":
            i += 1
            if i >= len(args):
                print(
                    "Usage: python3 -m yoke_core.engines.resync "
                    "[--detect-only | --fix] [--doctor-format] [--db-path PATH]",
                    file=sys.stderr,
                )
                return 1
            db_path = args[i]
        else:
            print(
                "Usage: python3 -m yoke_core.engines.resync "
                "[--detect-only | --fix] [--doctor-format] [--db-path PATH]",
                file=sys.stderr,
            )
            return 1
        i += 1

    # Resolve paths
    try:
        yoke_root = _resolve_yoke_root()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Linkage. Yoke auth failures fail-closed at the engine
    # boundary (control plane); per-project auth failures for other projects
    # are caught inside _fetch_gh_issues_per_project and surface as warnings.
    try:
        paired, local_orphans, gh_orphans, gh_by_project = stage1_linkage(
            db_path, yoke_root,
        )
    except ProjectGithubAuthError as exc:
        print(
            f"Error: GitHub auth failed for project '{exc.project}' "
            f"(code={exc.code}): {exc}",
            file=sys.stderr,
        )
        print(
            f"Repair: {repair_command_hint(exc, exc.project)}",
            file=sys.stderr,
        )
        return 2

    # Surface per-project auth failures as warnings. The sentinel pattern
    # (``_auth_error`` key on the per-project dict) is set by
    # _fetch_gh_issues_per_project when a non-Yoke project's auth resolution
    # fails; the engine continues with healthy projects but exits non-zero
    # overall so callers can detect partial failure.
    auth_failures: list[tuple[str, str, str]] = []
    for proj, value in list(gh_by_project.items()):
        if isinstance(value, dict) and "_auth_error" in value:
            auth_failures.append(
                (proj, value.get("_auth_error", ""), value.get("_repair_hint", "")),
            )
    if auth_failures and not doctor_format:
        print("=== Auth Failures (per-project, non-Yoke) ===")
        for proj, code, hint in auth_failures:
            print(f"  WARN: project '{proj}' auth failed (code={code})")
            if hint:
                print(f"    Repair: {hint}")
        print()

    # Sync-disabled projects (github_sync_mode=backlog_only) are excluded
    # from the run by design: no fetch, no orphan classification, no
    # repair. Named explicitly so an operator-invoked resync never looks
    # like it silently ignored a project. Not a failure — exit code
    # reflects the enabled projects only.
    sync_disabled_projects: list[tuple[str, str]] = []
    for proj, value in sorted(gh_by_project.items()):
        if _project_sync_disabled(value):
            sync_disabled_projects.append((proj, value.get(SYNC_DISABLED_KEY, "")))
    if sync_disabled_projects and not doctor_format:
        print("=== GitHub Sync Disabled (per-project) ===")
        for proj, mode in sync_disabled_projects:
            print(
                f"  NOTE: project '{proj}' github_sync_mode={mode} — "
                "backlog is DB-only; GitHub issue sync skipped"
            )
        print()

    paired_count = len(paired)
    local_orphan_count = len(local_orphans)
    gh_orphan_count = len(gh_orphans)
    total_checked = paired_count + local_orphan_count

    if not doctor_format:
        print("=== Stage 1: Linkage ===")
        print(f"Paired: {paired_count}")
        print(f"Local orphans: {local_orphan_count}")
        print(f"GitHub orphans: {gh_orphan_count}")
        print()

        if local_orphan_count > 0:
            print("Local orphans (no GitHub issue linked):")
            for oid, ofile, otype, oproj in local_orphans:
                print(f"  - {oid} ({otype}, project={oproj})")
            print()

        if gh_orphan_count > 0:
            print("GitHub orphans (no local item references them):")
            for num, title, state, proj in gh_orphans:
                print(f"  - #{num}: {title} ({state}, source={proj})")
            print()

    # Stage 1.5: Heavy fetch
    heavy_by_project = stage1_5_heavy_fetch(paired, gh_by_project)

    # Field comparison
    drifts = stage2_compare(paired, gh_by_project, heavy_by_project, db_path)
    drift_count = len(drifts)

    if not doctor_format:
        print("=== Stage 2: Field Comparison ===")
        print(f"Drifts found: {drift_count}")
        print()

        if drift_count > 0:
            for d in drifts:
                print(f"  - {d.id} | {d.field} | local={d.local} | github={d.github}")
            print()

    # Repair
    repaired = 0
    failed = 0

    if mode == "fix":
        if not doctor_format:
            print("=== Stage 3: Repair ===")

        # Repair local orphans. ``_repair_local_orphan_backlog`` returns
        # (success, reused, issue_num) so the engine can distinguish "created"
        # from "reused existing" in the log line.
        for oid, ofile, otype, oproj in local_orphans:
            if otype == "backlog":
                ok, reused, issue_num = _repair_local_orphan_backlog(oid, oproj)
                if ok:
                    repaired += 1
                    if not doctor_format:
                        if reused and issue_num:
                            print(
                                f"  FIXED: {oid} -- reused existing GitHub issue "
                                f"#{issue_num} (project={oproj})"
                            )
                        else:
                            print(
                                f"  FIXED: {oid} -- created GitHub issue "
                                f"(project={oproj})"
                            )
                else:
                    failed += 1
                    if not doctor_format:
                        print(
                            f"  FAILED: {oid} -- could not create GitHub issue "
                            f"(project={oproj})"
                        )
            else:
                if _repair_local_orphan_epic_task(oid, oproj, db_path):
                    repaired += 1
                    if not doctor_format:
                        print(f"  FIXED: {oid} -- created GitHub issue (project={oproj})")
                else:
                    failed += 1
                    if not doctor_format:
                        print(f"  FAILED: {oid} -- could not create GitHub issue (project={oproj})")

        # GitHub orphans: report only
        if gh_orphans and not doctor_format:
            for num, title, state, proj in gh_orphans:
                print(f"  REPORT: #{num} -- GitHub orphan: {title} ({state}, source={proj})")

        # Repair drifts
        for d in drifts:
            if _repair_drift(d, paired, db_path):
                repaired += 1
                if not doctor_format:
                    print(f"  FIXED: {d.id} -- {d.field} repaired")
            else:
                failed += 1
                if not doctor_format:
                    print(f"  FAILED: {d.id} -- {d.field} repair failed")

        if not doctor_format:
            print()

    # Doctor format output
    if doctor_format:
        _emit_doctor_format(local_orphans, gh_orphans, drifts, mode)

    # Summary
    print(
        f"Summary: {total_checked} checked, {paired_count} paired, "
        f"{local_orphan_count} local-orphans, {gh_orphan_count} github-orphans, "
        f"{drift_count} drifts, {repaired} repaired, {failed} failed"
    )

    # Exit code. Per-project auth failures force non-zero so callers can
    # detect partial-failure runs even when no orphans/drifts were found in
    # the healthy projects.
    total_issues = local_orphan_count + gh_orphan_count + drift_count
    if mode == "fix":
        if failed > 0 or auth_failures:
            return 1
        return 0
    if total_issues > 0 or auth_failures:
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
