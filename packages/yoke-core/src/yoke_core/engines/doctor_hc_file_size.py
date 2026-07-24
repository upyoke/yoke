"""HC-file-line-limit: authored file line-limit health check.

Reports authored violations as FAIL, temporary exceptions over limit
as WARN, and exclusion counts as informational context. The default limit
is 350; ``.yoke/project.config`` carries both the ``file_line_limit`` key
and the ``file_line_exception`` globs — the same checked-in policy the
pre-commit hook reads, so this check and the hook always agree.
"""

from __future__ import annotations

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_file_line_limit(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-file-line-limit: authored files over the project limit."""
    from yoke_core.domain import file_line_check
    from yoke_core.engines import doctor_report as _base
    from pathlib import Path

    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-file-line-limit", "Authored file 350-line limit", "PASS", "")
        return

    policy = file_line_check.resolved_policy(Path(repo_root))
    entries = file_line_check.inventory(repo_root=Path(repo_root))

    authored_violations = [
        e for e in entries
        if e.classification == file_line_check.Classification.AUTHORED
        and e.line_count > policy.limit
    ]
    exception_violations = [
        e for e in entries
        if e.classification == file_line_check.Classification.TEMPORARY_EXCEPTION
        and e.line_count > policy.limit
    ]
    excluded_counts = {
        "generated": sum(1 for e in entries if e.classification == file_line_check.Classification.GENERATED),
        "archive": sum(1 for e in entries if e.classification == file_line_check.Classification.ARCHIVE),
        "lockfile": sum(1 for e in entries if e.classification == file_line_check.Classification.LOCKFILE),
        "vendored": sum(1 for e in entries if e.classification == file_line_check.Classification.VENDORED),
        "data_asset": sum(1 for e in entries if e.classification == file_line_check.Classification.DATA_ASSET),
    }

    detail_lines = []
    if authored_violations:
        detail_lines.append(
            f"Authored over {policy.limit} ({len(authored_violations)}):"
        )
        for e in sorted(authored_violations, key=lambda x: -x.line_count)[:25]:
            detail_lines.append(f"  - {e.path}: {e.line_count} lines")
        if len(authored_violations) > 25:
            detail_lines.append(f"  ... and {len(authored_violations) - 25} more")
    if exception_violations:
        detail_lines.append(
            f"Temporary exceptions over {policy.limit} (warn-only): "
            f"{len(exception_violations)}"
        )
    detail_lines.append(
        "Excluded: "
        f"generated={excluded_counts['generated']}, "
        f"archive={excluded_counts['archive']}, "
        f"lockfile={excluded_counts['lockfile']}, "
        f"vendored={excluded_counts['vendored']}, "
        f"data_asset={excluded_counts['data_asset']}"
    )

    detail = "\n".join(detail_lines)

    if authored_violations:
        rec.record("HC-file-line-limit", "Authored file 350-line limit", "FAIL", detail)
    elif exception_violations:
        rec.record("HC-file-line-limit", "Authored file 350-line limit", "WARN", detail)
    else:
        rec.record("HC-file-line-limit", "Authored file 350-line limit", "PASS", detail)
