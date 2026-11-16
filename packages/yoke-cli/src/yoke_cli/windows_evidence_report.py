"""Read-only join of checked-in Windows expectations and durable QA runs."""

from __future__ import annotations

import json
from typing import Any, Iterable


def report(rows: list[dict[str, str]], receipts: Iterable[dict[str, Any]], *, yoke_release: str) -> list[dict[str, Any]]:
    latest: dict[str, tuple[int, dict[str, Any], dict[str, Any]]] = {}
    for receipt in receipts:
        raw = receipt.get("raw_result") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                continue
        if not isinstance(raw, dict):
            continue
        evidence = raw.get("evidence") or {}
        tag = evidence.get("windows_ledger") if isinstance(evidence, dict) else None
        if not isinstance(tag, dict) or tag.get("yoke_release") != yoke_release:
            continue
        if not receipt.get("completed_at"):
            continue
        ids = tag.get("row_ids")
        if not isinstance(ids, list):
            continue
        identity = receipt.get("id", receipt.get("run_id"))
        if not isinstance(identity, int):
            continue
        for identity_row in ids:
            if isinstance(identity_row, str) and identity > latest.get(identity_row, (-1, {}, {}))[0]:
                latest[identity_row] = (identity, receipt, tag)
    result = []
    for row in rows:
        state, receipt_id, facts = "unproven", None, None
        matched = latest.get(row["row_id"])
        if matched:
            receipt_id, receipt, facts = matched
        if matched and facts.get("os") == "windows" and all(
            facts.get(key) for key in ("edition", "build", "harness_version")
        ):
            outcome = facts.get("observed_outcome")
            expected = row["expectation"]
            state = "failed"
            if receipt.get("verdict") == "pass":
                if expected == "must-pass" and outcome == "passed":
                    state = "proven"
                elif expected == "expected-refusal" and outcome == "refused" and facts.get("reason") == row["reason"]:
                    state = "refused"
                elif expected == "not-applicable" and outcome == "not_applicable" and facts.get("reason") == row["reason"]:
                    state = "not-applicable"
            if expected == "upstream-limitation" and outcome == "upstream_limitation":
                state = "upstream-limitation"
        result.append({**row, "state": state, "qa_run_id": receipt_id, "native_facts": facts})
    return result
