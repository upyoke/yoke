"""Render the unified ``## DB Claim`` body section.

Pure render helper — parses ``db_mutation_profile`` and
``db_compatibility_attestation`` JSON payloads from an item row and
renders the operator-facing ``## DB Claim`` section.  Zero DB writes,
zero file writes, zero side effects.

Internal storage stays split across ``db_mutation_profile`` and
``db_compatibility_attestation``; the rendered body presents a single
section so operators see one DB-claim concept rather than two raw JSON
blobs.

Imported by ``yoke_core.domain.render_body``; the parent module
exposes ``DB_CLAIM_HEADING``, ``DB_CLAIM_ATTESTATION_SUBHEADING``, and
``render_db_claim_section`` as the stable body-rendering surface.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


DB_CLAIM_HEADING = "## DB Claim"
DB_CLAIM_ATTESTATION_SUBHEADING = "### Safety attestation"

__all__ = (
    "DB_CLAIM_HEADING",
    "DB_CLAIM_ATTESTATION_SUBHEADING",
    "render_db_claim_section",
)


def _parse_json_payload(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _format_affected_surface(entry: Dict[str, Any]) -> str:
    table = entry.get("table", "")
    columns = entry.get("columns") or []
    if columns:
        col_fragment = ", ".join(f"`{c}`" for c in columns)
        return f"`{table}` (columns: {col_fragment})"
    return f"`{table}` (whole table)"


def _profile_lines(profile: Dict[str, Any]) -> List[str]:
    """Render the profile-half bullet list of the unified DB Claim section."""
    lines: List[str] = []
    state = profile.get("state")
    if state:
        lines.append(f"- **State:** `{state}`")
    if profile.get("model_name"):
        lines.append(f"- **Model:** `{profile['model_name']}`")
    if profile.get("mutation_intent"):
        lines.append(f"- **Intent:** `{profile['mutation_intent']}`")
    if profile.get("compatibility_class"):
        lines.append(
            f"- **Compatibility class:** `{profile['compatibility_class']}`"
        )

    if profile.get("migration_strategy"):
        lines.append(
            f"- **Migration strategy:** `{profile['migration_strategy']}`"
        )
    if profile.get("migration_strategy_justification"):
        lines.append(
            f"- **Migration strategy justification:** "
            f"{profile['migration_strategy_justification']}"
        )

    modules = profile.get("migration_modules") or []
    if modules:
        lines.append("- **Migration modules:**")
        for module in modules:
            lines.append(f"  - `{module}`")

    schema_kinds = profile.get("schema_kinds") or []
    if schema_kinds:
        lines.append(
            "- **Schema kinds:** " + ", ".join(f"`{k}`" for k in schema_kinds)
        )

    data_kinds = profile.get("data_kinds") or []
    if data_kinds:
        lines.append(
            "- **Data kinds:** " + ", ".join(f"`{k}`" for k in data_kinds)
        )

    surfaces = profile.get("affected_surfaces") or []
    if surfaces:
        lines.append("- **Affected surfaces:**")
        for surface in surfaces:
            lines.append(f"  - {_format_affected_surface(surface)}")

    if "count_preserving" in profile:
        lines.append(
            f"- **Count preserving:** `{str(bool(profile['count_preserving'])).lower()}`"
        )

    return lines


def _attestation_lines(attestation: Dict[str, Any]) -> List[str]:
    """Render the attestation-half bullet list of the unified DB Claim section."""
    lines: List[str] = []
    frozen_at = attestation.get("frozen_at")
    if frozen_at:
        lines.append(f"- **Frozen at:** `{frozen_at}`")
    else:
        lines.append("- **Frozen at:** _(not yet frozen)_")

    readers_writers = attestation.get("pre_merge_readers_writers") or []
    if readers_writers:
        lines.append("- **Pre-merge readers/writers:**")
        for entry in readers_writers:
            path = entry.get("path", "")
            symbol = entry.get("symbol") or ""
            role = entry.get("role", "")
            if symbol:
                lines.append(f"  - `{path}::{symbol}` ({role})")
            else:
                lines.append(f"  - `{path}` ({role})")

    invariants = attestation.get("invariants") or []
    if invariants:
        lines.append("- **Invariants:**")
        for inv in invariants:
            lines.append(f"  - {inv}")

    commands = attestation.get("rehearsal_commands") or []
    if commands:
        lines.append("- **Rehearsal commands:**")
        for cmd in commands:
            lines.append(f"  - `{cmd}`")

    residual = attestation.get("residual_risk_notes")
    if residual:
        lines.append(f"- **Residual risk notes:** {residual}")

    outcomes = attestation.get("rehearsal_outcomes") or []
    if outcomes:
        lines.append("- **Rehearsal outcomes:**")
        for outcome in outcomes:
            cmd = outcome.get("command", "")
            verdict = outcome.get("verdict", "")
            if not verdict and "returncode" in outcome:
                returncode = outcome.get("returncode")
                verdict = "pass" if returncode == 0 else f"fail:{returncode}"
            observed = outcome.get("observed_at") or outcome.get("ran_at") or ""
            tail = f" @ {observed}" if observed else ""
            lines.append(f"  - `{cmd}` → `{verdict}`{tail}".rstrip())

    escalations = attestation.get("class_escalations") or []
    if escalations:
        lines.append("- **Class escalations:**")
        for esc in escalations:
            from_class = esc.get("from", "")
            to_class = esc.get("to", "")
            source = esc.get("source", "")
            reason = esc.get("reason", "")
            header = f"`{from_class}` → `{to_class}`"
            suffix_parts = [p for p in (source, reason) if p]
            suffix = f" ({': '.join(suffix_parts)})" if suffix_parts else ""
            lines.append(f"  - {header}{suffix}")

    return lines


def render_db_claim_section(profile_raw: Any, attestation_raw: Any) -> Optional[str]:
    """Render the unified ``## DB Claim`` body section.

    Internal storage stays split across ``db_mutation_profile`` and
    ``db_compatibility_attestation``; the rendered body presents a
    single section so operators see one DB-claim concept rather than
    two raw JSON blobs.

    Render policy:
      * ``state="declared"`` → render the full claim, with a
        ``### Safety attestation`` sub-section when the attestation
        carries authored content or a freeze stamp.
      * ``state="none"`` (or absent) → render nothing.  Stamped
        attestations on negative claims are accepted residue and do
        not surface in the body.
      * Malformed JSON on either field is treated as absence.
    """
    profile = _parse_json_payload(profile_raw)
    if profile is None or profile.get("state") != "declared":
        return None

    chunks: List[str] = [DB_CLAIM_HEADING, ""]
    chunks.extend(_profile_lines(profile))

    attestation = _parse_json_payload(attestation_raw) or {}
    if attestation:
        att_lines = _attestation_lines(attestation)
        if att_lines:
            chunks.append("")
            chunks.append(DB_CLAIM_ATTESTATION_SUBHEADING)
            chunks.append("")
            chunks.extend(att_lines)

    return "\n".join(chunks)
