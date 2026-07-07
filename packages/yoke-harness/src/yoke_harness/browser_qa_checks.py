"""Browser QA validation and payload helpers."""

from __future__ import annotations

import json
import re
import socket
import subprocess
from typing import Any, Dict, List, Optional
import urllib.request

from yoke_harness.browser_qa_results import SCREENSHOT_ACTIONS, log


def is_screenshot_step(step: Dict[str, Any]) -> bool:
    return (
        isinstance(step, dict)
        and step.get("action") in SCREENSHOT_ACTIONS
        and bool(step.get("capture"))
    )


def validate_reachability(base_url: str) -> Optional[str]:
    host = re.sub(r"https?://", "", base_url).split("/")[0].split(":")[0]
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror:
        return f"DNS resolution failed for {host}"
    try:
        request = urllib.request.Request(base_url, method="HEAD")
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 400:
                return f"HTTP probe failed for {base_url} (status: {response.status})"
    except Exception:
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "-L",
                    "--max-time",
                    "10",
                    base_url,
                ],
                capture_output=True,
                text=True,
            )
            code = result.stdout.strip()
            if not code or code[0] not in ("2", "3"):
                return f"HTTP probe failed for {base_url} (status: {code})"
        except Exception as exc:
            return f"HTTP probe failed for {base_url}: {exc}"
    return None


def validate_freshness_inputs(
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> Optional[str]:
    if bool(expected_branch) == bool(expected_sha):
        return None
    return (
        "Deployment freshness validation requires both --expected-branch and "
        "--expected-sha. Provide the branch name and HEAD SHA together."
    )


def validate_deployed_sha(
    project: str,
    expected_branch: str,
    expected_sha: str,
    *,
    deployed_sha: Optional[str],
    deployment_recorded: bool,
) -> Optional[str]:
    if not deployment_recorded:
        return (
            f"No ephemeral environment record found for branch '{expected_branch}' "
            f"in project '{project}'. No deployment was recorded for the expected branch."
        )
    if not deployed_sha:
        return (
            f"Ephemeral environment for branch '{expected_branch}' has no deployed_sha. "
            f"No deployment was recorded for the expected branch."
        )
    if deployed_sha != expected_sha:
        return (
            f"Deployed SHA mismatch for branch '{expected_branch}': "
            f"expected {expected_sha}, but environment has {deployed_sha}."
        )
    log(f"Freshness check passed: branch={expected_branch}, sha={expected_sha}")
    return None


def build_code_identity(
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> Dict[str, str]:
    payload: Dict[str, str] = {}
    if expected_branch:
        payload["branch"] = expected_branch
    if expected_sha:
        payload["sha"] = expected_sha
    return payload


def build_run_payload(
    *,
    project: str,
    base_url: str,
    code_identity: Dict[str, str],
    freshness_validated: bool,
    verdict: Optional[str] = None,
    execution_status: Optional[str] = None,
    errors: str = "",
    artifacts: Optional[List[str]] = None,
    expected_screenshots: int = 0,
    recorded_screenshots: int = 0,
    note: Optional[str] = None,
) -> str:
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
        payload["artifacts"] = artifacts
    if expected_screenshots > 0:
        payload["expected_screenshots"] = expected_screenshots
        payload["recorded_screenshots"] = recorded_screenshots
    if note:
        payload["note"] = note
    return json.dumps(payload, sort_keys=True)


__all__ = [
    "build_code_identity",
    "build_run_payload",
    "is_screenshot_step",
    "validate_deployed_sha",
    "validate_freshness_inputs",
    "validate_reachability",
]
