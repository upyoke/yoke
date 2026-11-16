"""Native machine evidence tags shared by adapters, persistence and reports."""

from __future__ import annotations

from typing import Any

ROW_IDS_KEY = "windows_ledger_row_ids"
EVIDENCE_KEY = "windows_ledger"
FACTS = ("os", "edition", "build", "harness_version", "yoke_release", "observed_outcome", "reason")


def tag_receipt(config: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Copy execution-bound case tags; absence of native facts never invents proof."""
    ids = config.get(ROW_IDS_KEY)
    if ids is None:
        return evidence
    if not isinstance(ids, list) or not ids or any(
        not isinstance(value, str) or not value.startswith("windows-") for value in ids
    ):
        raise ValueError("windows_ledger_tags_invalid: set windows_ledger_row_ids to a nonempty list of ledger row ids")
    connection = evidence.get("connection") or {}
    existing = evidence.get(EVIDENCE_KEY) or {}
    facts = {key: existing.get(key, connection.get(key)) for key in FACTS}
    return {**evidence, EVIDENCE_KEY: {**facts, "row_ids": list(dict.fromkeys(ids))}}
