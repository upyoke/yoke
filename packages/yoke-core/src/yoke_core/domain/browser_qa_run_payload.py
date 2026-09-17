"""The structured result a Browser QA run records about itself.

``raw_result`` is the only durable account of what a run did, and the
merge gate reads the commit out of it, so what goes in here is evidence
rather than intention: the code identity carries a commit some source
verified about the target, never the one the caller asked for.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from yoke_contracts.qa_artifact_read import artifact_read_command


def _build_code_identity(
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> Dict[str, str]:
    """Build the code identity payload recorded on browser QA runs.

    ``expected_sha`` is the commit a freshness source reported about the
    target, not the commit the caller requested — the two are equal only
    because a source compared them, and recording the request instead
    would turn an unasked question into a proof.
    """
    payload: Dict[str, str] = {}
    if expected_branch:
        payload["branch"] = expected_branch
    if expected_sha:
        payload["sha"] = expected_sha
    return payload


def _build_run_payload(
    *,
    project: str,
    base_url: str,
    code_identity: Dict[str, str],
    freshness_validated: bool,
    verdict: Optional[str] = None,
    execution_status: Optional[str] = None,
    errors: str = "",
    artifacts: Optional[List[str]] = None,
    requirement_id: Optional[int] = None,
    artifact_ids: Optional[List[int]] = None,
    expected_screenshots: int = 0,
    recorded_screenshots: int = 0,
    note: Optional[str] = None,
) -> str:
    """Build the structured raw_result payload for browser QA runs."""
    payload: Dict[str, Any] = {
        "project": project,
        "base_url": base_url,
        "freshness_validated": freshness_validated,
    }
    if code_identity:
        payload["code_identity"] = code_identity
    if verdict:
        payload["verdict"] = verdict
    if execution_status:
        payload["execution_status"] = execution_status
    if errors:
        payload["errors"] = errors
    if artifacts:
        # Machine-local capture scratch: useful to the capturing process,
        # refused by the path guard of the session that reviews it later.
        payload["artifacts"] = artifacts
    if artifact_ids:
        payload["artifact_ids"] = list(artifact_ids)
        if requirement_id is not None:
            payload["artifact_reads"] = [
                artifact_read_command(int(requirement_id), int(artifact_id))
                for artifact_id in artifact_ids
            ]
    if expected_screenshots > 0:
        payload["expected_screenshots"] = expected_screenshots
        payload["recorded_screenshots"] = recorded_screenshots
    if note:
        payload["note"] = note
    return json.dumps(payload, sort_keys=True)
