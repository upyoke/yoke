"""HC-path-integrity: shadow-mode path-integrity verifier surface.

Read-only doctor surface. Surfaces the most recent
``path_integrity_runs.status`` per registered project, plus the count
of unrepaired failures across all runs for that project. This HC never
runs the verifier itself — it summarises whatever rows the verifier
last produced. Operators trigger fresh verifier runs via
``python3 -m yoke_core.domain.path_integrity verify``.

Disposition vocabulary:

* PASS — every project's most recent run is ``passed`` and all runs
  have zero unrepaired failures.
* WARN — a project's most recent run is ``failed`` with one or more
  unrepaired failures, or a project has lingering ``running`` rows
  from prior crashed processes that the verifier has not yet closed.
* PASS with informational note — projects that lack substrate produce
  a ``skipped`` row; the HC mentions them but does not raise WARN.
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-path-integrity"
_HC_DESC = "Path-integrity verifier surface (shadow-mode)"


def hc_path_integrity(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    if not _base._table_exists(conn, "path_integrity_runs"):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "path_integrity_runs table missing — verifier not "
            "provisioned yet",
        )
        return
    if not _base._table_exists(conn, "projects"):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "no projects table; nothing to summarise",
        )
        return

    rows = query_rows(
        conn,
        """
        SELECT p.id AS project_id,
               (SELECT status
                  FROM path_integrity_runs r
                 WHERE r.project_id = p.id
                 ORDER BY r.id DESC LIMIT 1) AS latest_status,
               (SELECT commit_sha
                  FROM path_integrity_runs r
                 WHERE r.project_id = p.id
                 ORDER BY r.id DESC LIMIT 1) AS latest_commit,
               (SELECT COALESCE(SUM(unrepaired_failure_count), 0)
                  FROM path_integrity_runs r
                 WHERE r.project_id = p.id) AS unrepaired_total,
               (SELECT COUNT(*)
                  FROM path_integrity_runs r
                 WHERE r.project_id = p.id
                   AND r.status = 'running') AS stale_running
        FROM projects p
        ORDER BY p.id
        """,
    )

    issues: List[str] = []
    info: List[str] = []
    for row in rows:
        project_id = row["project_id"]
        latest_status = row["latest_status"]
        commit_sha = row["latest_commit"] or "-"
        unrepaired = int(row["unrepaired_total"] or 0)
        stale_running = int(row["stale_running"] or 0)

        if latest_status is None:
            info.append(
                f"- {project_id}: no path_integrity_runs rows yet"
            )
            continue

        line = (
            f"- {project_id}: status={latest_status} "
            f"commit={commit_sha} unrepaired_failures={unrepaired}"
        )
        if stale_running:
            line += f" stale_running={stale_running}"

        if latest_status == "failed" or unrepaired > 0:
            issues.append(line)
        elif stale_running > 0:
            issues.append(line)
        elif latest_status == "skipped":
            info.append(
                f"- {project_id}: skipped (no substrate or capability)"
            )
        else:
            info.append(line)

    if issues:
        rec.record(
            _HC_NAME, _HC_DESC, "WARN", "\n".join(issues + info),
        )
    else:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "\n".join(info) if info else "",
        )
