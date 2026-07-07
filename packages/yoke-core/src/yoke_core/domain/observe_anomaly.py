"""Anomaly classification for observe telemetry records."""

from __future__ import annotations

import re
from typing import List

from yoke_core.domain.observe_parsing import EventRecord

def detect_anomalies(rec: EventRecord) -> List[str]:
    """Detect anomalies in an event record. Updates ``rec.anomalies`` in place
    and returns the list."""
    anomalies: List[str] = []

    # 1. nonzero_exit
    if rec.exit_code is not None and rec.exit_code > 0:
        anomalies.append("nonzero_exit")

    # 2. generated_view_write
    if rec.tool_name in ("Write", "Edit") and rec.file_path:
        generated_patterns = [
            r"\.yoke/BOARD\.md(?:\.ts)?$",
        ]
        for pat in generated_patterns:
            if re.search(pat, rec.file_path):
                anomalies.append("generated_view_write")
                break

    # 3. nested_cli
    if rec.tool_name == "Bash" and rec.command:
        cmd_stripped = rec.command.strip()
        if re.search(r"(?:^|[;&|]\s*|[$]\()\s*claude\b", cmd_stripped):
            anomalies.append("nested_cli")

    # 4. unattributed (main session only)
    if rec.item_id is None and rec.agent_type is None:
        anomalies.append("unattributed")

    # 5. lifecycle_mutation
    if rec.tool_name == "Bash" and rec.command and not rec.is_failure:
        lifecycle_dml_patterns = [
            r"UPDATE\s+items\b.*\bstatus\s*=",
            r"UPDATE\s+items\b.*\bdeploy_stage\s*=",
            r"UPDATE\s+epic_tasks\b.*\bstatus\s*=",
            r"DELETE\s+FROM\s+(?:items|epic_tasks|events)\b",
            r"INSERT\s+INTO\s+events\b",
        ]
        for ldp in lifecycle_dml_patterns:
            if re.search(ldp, rec.command, re.IGNORECASE):
                anomalies.append("lifecycle_mutation")
                break

    # 6. benign_failure
    if rec.is_failure:
        err_str = rec.hook_error or ""
        benign_patterns = [
            "String to replace not found",
            "old_string not found in file",
            "No files matched",
            "No matches found",
        ]
        for bp in benign_patterns:
            if bp.lower() in err_str.lower():
                anomalies.append("benign_failure")
                break

    # 7. structured_exit
    if rec.is_failure:
        combined = (rec.hook_error or "") + " " + (rec.response_text or "")
        structured_patterns = [
            r"[Aa]waiting human approval",
            r"[Aa]waiting approval",
            r"[Aa]pproval gate",
        ]
        for sp in structured_patterns:
            if re.search(sp, combined):
                if "structured_exit" not in anomalies:
                    anomalies.append("structured_exit")
                break

    rec.anomalies = anomalies
    return anomalies
