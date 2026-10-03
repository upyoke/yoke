"""Human-readable rendering of the typed QA gate summary."""

from __future__ import annotations

from typing import Any, Dict


def _format_text(summary: Dict[str, Any]) -> str:
    lines = [f"QA Gate Summary - {summary['target']} -> {summary['transition']}"]
    if not summary["qa_tables_present"]:
        lines.append("  GATE_QA_SCHEMA_MISSING: qa_requirements table not present.")
        return "\n".join(lines)
    if summary["no_requirements"]:
        lines.append("  GATE_QA_REQUIREMENTS_EMPTY: No QA requirements registered.")
        return "\n".join(lines)
    status = "SATISFIED" if summary["satisfied"] else "UNSATISFIED"
    lines.append(f"  Status: {status}")
    lines.append(
        "  Tree freshness: not evaluated here. The terminal gate also requires "
        "each passing run to name the merged tree."
    )
    lines.append(f"  Blocking unsatisfied: {summary['blocking_unsatisfied_count']}")
    lines.append(f"  Browser unsatisfied:  {summary['browser_unsatisfied_count']}")
    lines.append(f"  E2E unsatisfied:      {summary['e2e_unsatisfied_count']}")
    lines.append("  Requirements:")
    for req in summary["requirements"]:
        marker = (
            "RETIRED"
            if req.get("retracted_at")
            else ("OK" if req["satisfied"] else "NO")
        )
        waived = " (waived)" if req["waived_at"] else ""
        lines.append(
            f"    {marker} #{req['id']} "
            f"{req['method_id'] or req['qa_kind']} "
            f"phase={req['qa_phase']} blocking_mode={req['blocking_mode']}{waived}"
        )
        latest = req["latest_run"]
        if latest:
            lines.append(
                f"        latest run #{latest['id']}: verdict={latest['verdict']} "
                f"runner={latest['performed_by']} at {latest['created_at']}"
            )
        if req["human_review"]:
            lines.append(f"        {req['human_review']['detail']}")
            lines.append(f"        {req['human_review']['recovery']}")
    return "\n".join(lines)
