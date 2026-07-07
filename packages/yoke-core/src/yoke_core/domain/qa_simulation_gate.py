"""Integration simulation gate for epic items.

Owns ``check_epic_simulation_gate`` plus its inner advisory helper. The
authoritative integration simulation gate honours ``YOKE_SKIP_SIMULATION=1``
for bypass and the ``CLEAN`` / ``GAPS FOUND`` result vocabulary, with
blocking-pattern detection on the simulation body text.

Consumers should keep importing via ``yoke_core.domain.qa_gates`` (which
re-exports ``check_epic_simulation_gate``) so their import paths remain stable.
"""

from __future__ import annotations

import os
import re
import sys

from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.qa_gate_definitions import GateResult
from yoke_core.domain.sql_json import json_get


def _emit_non_critical_advisory(body_text: str) -> None:
    """Emit a non-critical GAPS-FOUND advisory to stderr.

    Echoes the simulation body's ``## Gaps Found:`` summary and ``### GAP #``
    titles so operators can review without blocking the transition.
    """
    print(
        "Integration simulation gate: GAPS FOUND (non-critical) -- proceeding.",
        file=sys.stderr,
    )
    gap_summary = re.findall(r"^## Gaps Found:.*$", body_text, re.MULTILINE)
    for summary in gap_summary:
        print(summary, file=sys.stderr)
    gap_titles = re.findall(r"^### GAP #.*$", body_text, re.MULTILINE)
    for title in gap_titles:
        print(f"  {title}", file=sys.stderr)


def check_epic_simulation_gate(epic_id: int, db_path: str) -> GateResult:
    """Authoritative integration simulation gate for epic items."""
    if os.environ.get("YOKE_SKIP_SIMULATION") == "1":
        print(
            f"WARNING: Integration simulation gate bypassed via YOKE_SKIP_SIMULATION for YOK-{epic_id}",
            file=sys.stderr,
        )
        return GateResult(passed=True)

    conn = connect(db_path)
    try:
        # Simulation data lives in qa_runs joined to qa_requirements
        # (qa_kind='simulation', phase in success_policy JSON).
        # Result is derived: verdict 'pass' -> CLEAN, 'fail' -> GAPS FOUND.
        # Body comes from raw_result (JSON with $.body, or raw text).
        row = query_one(
            conn,
            f"""SELECT qr.id,
                      qreq.item_id,
                      CASE qr.verdict
                        WHEN 'pass' THEN 'CLEAN'
                        WHEN 'fail' THEN 'GAPS FOUND'
                        ELSE ''
                      END as result,
                      CASE WHEN substr(qr.raw_result, 1, 1) = '{{'
                           THEN COALESCE({json_get('qr.raw_result', '$.body')}, '')
                           ELSE qr.raw_result
                      END as body,
                      qr.created_at
               FROM qa_runs qr
               JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id
               WHERE qreq.qa_kind = 'simulation'
                 AND qreq.item_id = %s
                 -- deliberate case-sensitive match against internal JSON-literal values
                 AND (qreq.success_policy LIKE '%%"phase":"integration"%%'
                      OR qreq.success_policy LIKE '%%integration%%')
               ORDER BY qr.created_at DESC, qr.id DESC
               LIMIT 1""",
            (epic_id,),
        )
    except Exception:
        row = None
    finally:
        conn.close()

    if not row:
        return GateResult(
            passed=False,
            errors=[
                f"Error: No integration simulation found for epic YOK-{epic_id}.",
                f"Run '/yoke simulate {epic_id} --phase integration' before advancing.",
            ],
        )

    result = row["result"] or ""
    body = row["body"] or ""

    if result == "CLEAN":
        print("Integration simulation gate: CLEAN -- proceeding.", file=sys.stderr)
        return GateResult(passed=True)

    if result == "GAPS FOUND":
        # Check for blocking gaps
        blocking_pattern = re.compile(
            r"Severity:.*\[CRITICAL\]|^### CRITICAL|Recommendation:\s*(BLOCK|REQUIRED)",
            re.IGNORECASE | re.MULTILINE,
        )
        blocking_match = blocking_pattern.search(body)
        if blocking_match:
            return GateResult(
                passed=False,
                errors=[
                    f"Error: Integration simulation for epic YOK-{epic_id} has blocking gaps.",
                    "",
                    "Blocking gaps found:",
                    blocking_match.group(0),
                    "",
                    f"Resolve gaps and re-run '/yoke simulate {epic_id} --phase integration', or use --skip-simulation to bypass.",
                ],
            )

        # Non-critical gaps -- allow with advisory
        _emit_non_critical_advisory(body)
        return GateResult(passed=True)

    if result == "":
        # Empty result -- check if body has meaningful content
        content_pattern = re.compile(
            r"GAP #|Severity:|Recommendation:|### CRITICAL|### WARNING|### NOTE|Gaps Found:",
            re.IGNORECASE,
        )
        if not content_pattern.search(body):
            return GateResult(
                passed=False,
                errors=[
                    f"Error: Integration simulation for epic YOK-{epic_id} has empty result and body.",
                    f"Run '/yoke simulate {epic_id} --phase integration' before advancing.",
                ],
            )
        # Has content but empty result -- treat as GAPS FOUND
        blocking_pattern = re.compile(
            r"Severity:.*\[CRITICAL\]|^### CRITICAL|Recommendation:\s*(BLOCK|REQUIRED)",
            re.IGNORECASE | re.MULTILINE,
        )
        if blocking_pattern.search(body):
            return GateResult(
                passed=False,
                errors=[
                    f"Error: Integration simulation for epic YOK-{epic_id} has blocking gaps.",
                ],
            )
        _emit_non_critical_advisory(body)
        return GateResult(passed=True)

    # Unknown result
    return GateResult(
        passed=False,
        errors=[
            f"Error: Integration simulation for epic YOK-{epic_id} has unrecognized result: '{result}'.",
            "Only 'CLEAN' or 'GAPS FOUND' are valid simulation results.",
            f"Run '/yoke simulate {epic_id} --phase integration' to generate a valid report.",
        ],
    )
