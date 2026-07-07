"""Doctor HC for detecting mutated ``qa_runs`` rows.

The ``qa_runs_verdict_immutable`` trigger refuses post-completion writes
to ``verdict`` and ``raw_result`` on the live DB.  This HC catches drift
on older databases or environments where the trigger somehow ended up
absent: it scans for ``qa_runs`` rows whose ``verdict='fail'`` is paired
with a ``raw_result`` body that contains resolution-narrative phrases
the workflow would only have appended after deciding the original
failure was resolved.

Heuristic: search failed runs for explicit resolution language such as
"resolved", "supersed", "PASS", "9/9 PASS", "all gaps closed", or
"resolution". A fail verdict paired with later resolution narrative is
the fingerprint of an overwritten run rather than a genuinely failing run.

Emits WARN with the affected run ids and the reminder that resolution
narrative belongs in a fresh ``qa run-add`` row.  PASS when no such
rows exist.  Historical rows discovered before the trigger landed are
informational findings, not failures.
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-qa-runs-mutated"
_HC_DESC = "qa_runs rows whose raw_result mixes failing verdict with resolution narrative"


_RESOLUTION_PHRASES = (
    "resolved by",
    "all gaps closed",
    "all gaps resolved",
    "9/9 PASS",
    "supersedes",
    "supersed",
    "resolution",
)

# Rows that carry this token in their raw_result have been reviewed
# by a governed normalization run and stamped with a
# ``normalization_disposition`` field (see
# ``yoke_core.db.migrations.split_qa_runs_raw_result``).  Skip
# them in the heuristic so the per-row review is not re-flagged on
# every doctor run.  The token is intentionally specific so no
# organic body coincidentally carries it.
_NORMALIZATION_DISPOSITION_TOKEN = "normalization_disposition"


def hc_qa_runs_mutated(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    if not _base._table_exists(conn, "qa_runs"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "qa_runs table missing -- skipping")
        return

    # Fetch every fail-verdict row whose raw_result is non-empty.  The
    # set is small (failing simulations + verifications) so we can scan
    # for resolution-language phrases in Python rather than juggling
    # brittle SQL LIKE chains.
    rows = query_rows(
        conn,
        """
        SELECT id, qa_requirement_id, raw_result, created_at
        FROM qa_runs
        WHERE verdict = 'fail'
          AND raw_result IS NOT NULL
          AND raw_result <> ''
        ORDER BY id DESC
        LIMIT 500
        """,
    )

    suspect: List[dict] = []
    for row in rows:
        raw = row["raw_result"] or ""
        if _NORMALIZATION_DISPOSITION_TOKEN in raw:
            # Already reviewed and stamped by a governed normalization
            # migration; the disposition is the authoritative record.
            continue
        body = raw.lower()
        if any(phrase.lower() in body for phrase in _RESOLUTION_PHRASES):
            suspect.append(row)

    if not suspect:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    issues: List[str] = [
        f"- {len(suspect)} qa_runs row(s) with verdict='fail' whose "
        "raw_result contains resolution-narrative phrases. Resolution "
        "evidence belongs in a fresh `qa run-add` row, not appended "
        "to the failing run. The qa_runs_verdict_immutable trigger "
        "blocks future writes, but historical rows on older DBs may "
        "still drift -- surface them so the operator can record paired "
        "pass runs if needed.",
    ]
    for row in suspect[:10]:
        issues.append(
            f"  - qa_run #{row['id']} (req #{row['qa_requirement_id']}) "
            f"created {row['created_at']}"
        )
    if len(suspect) > 10:
        issues.append(f"  - ... and {len(suspect) - 10} more")
    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))
