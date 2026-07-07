"""Freshness, reachability, and run-payload helpers for Browser QA.

Owns:

- ``_resolve_repo_root`` and ``_json_get`` filesystem/JSON utilities used by
  the orchestrator.
- ``_validate_reachability`` — DNS + HTTP probe of the target base URL.
- ``_validate_freshness_inputs`` and ``_validate_deployed_sha`` — deployment
  freshness gating. The ``ephemeral_environments`` row is read server-side
  by ``qa.browser_context.get``; ``_validate_deployed_sha`` is the pure
  client-side comparison over that payload.
- ``_build_code_identity`` and ``_build_run_payload`` — structured raw_result
  payload builders.

``_validate_deployed_sha`` calls ``_log`` via the parent ``browser_qa``
module so test patches such as ``mock.patch("...browser_qa._log")`` apply
without rebinding sibling-local names.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _resolve_repo_root() -> str:
    """Resolve main worktree root."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("worktree "):
                    return line[len("worktree "):]
    except Exception:
        pass

    # Fallback
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    from yoke_core.api.repo_root import find_repo_root

    return str(find_repo_root(Path(__file__)))


def _json_get(data: Any, key: str) -> Any:
    """Safely extract a value from a dict by dotpath."""
    if not isinstance(data, dict):
        return None
    keys = key.split(".")
    val = data
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        elif isinstance(val, list):
            try:
                val = val[int(k)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if val is None:
            return None
    return val


def _validate_reachability(base_url: str) -> Optional[str]:
    """Validate that base_url is reachable. Returns error message or None."""
    # Extract hostname
    host = re.sub(r"https?://", "", base_url).split("/")[0].split(":")[0]

    # DNS probe
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror:
        return f"DNS resolution failed for {host}"

    # HTTP probe
    try:
        import urllib.request
        req = urllib.request.Request(base_url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                return f"HTTP probe failed for {base_url} (status: {resp.status})"
    except Exception:
        # Fallback to curl for better compat
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-L",
                 "--max-time", "10", base_url],
                capture_output=True,
                text=True,
            )
            code = result.stdout.strip()
            if not code or code[0] not in ("2", "3"):
                return f"HTTP probe failed for {base_url} (status: {code})"
        except Exception as e:
            return f"HTTP probe failed for {base_url}: {e}"

    return None


def _validate_freshness_inputs(
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> Optional[str]:
    """Validate the freshness input contract before scenario execution."""
    has_expected_branch = bool(expected_branch)
    has_expected_sha = bool(expected_sha)
    if has_expected_branch == has_expected_sha:
        return None
    return (
        "Deployment freshness validation requires both --expected-branch and "
        "--expected-sha. Provide the branch name and HEAD SHA together."
    )


def _validate_deployed_sha(
    project: str,
    expected_branch: str,
    expected_sha: str,
    *,
    deployed_sha: Optional[str],
    deployment_recorded: bool,
) -> Optional[str]:
    """Validate that the ephemeral environment deployed the expected SHA.

    Pure comparison over the ``qa.browser_context.get`` payload
    (``deployed_sha`` + ``deployment_recorded``). Returns None on success,
    or an error message string on failure. Logs the validated branch and
    SHA on success for auditability.
    """
    # Lazy import so tests patching browser_qa._log apply.
    from yoke_core.domain import browser_qa as _bqa

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

    _bqa._log(f"Freshness check passed: branch={expected_branch}, sha={expected_sha}")
    return None


def _build_code_identity(
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> Dict[str, str]:
    """Build the code identity payload recorded on browser QA runs."""
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
        payload["artifacts"] = artifacts
    if expected_screenshots > 0:
        payload["expected_screenshots"] = expected_screenshots
        payload["recorded_screenshots"] = recorded_screenshots
    if note:
        payload["note"] = note
    return json.dumps(payload, sort_keys=True)
