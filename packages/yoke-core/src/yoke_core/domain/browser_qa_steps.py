"""Step execution and qa_run/qa_artifact recording helpers.

Owns:

- ``_SCREENSHOT_ACTIONS`` and ``_is_screenshot_step`` — vocabulary for
  artifact-producing screenshot steps (kept colocated with the predicate).
- ``_execute_step`` — single-step dispatch through the browser daemon.
- ``_record_run`` / ``_complete_run`` / ``_record_artifact`` — dispatcher
  delegates (``qa.run.add`` / ``qa.run.complete`` / ``qa.artifact.add``)
  so the writes work over both transports; failures degrade to ``None`` /
  no-op exactly as the prior in-process delegates did.
- ``_durable_artifact_handle`` — upload-at-record: mint a presigned PUT
  through ``qa.artifact.presign``, upload the capture over plain HTTPS,
  and return the S3 handle to record. Any miss (no bucket declared,
  presign denied, upload failure) degrades to an explicit ``local``
  handle — captured evidence is recorded either way; durability is the
  opt-in layer.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


_SCREENSHOT_ACTIONS = frozenset({"screenshot"})

_BROWSER_EXECUTOR_TYPE = "browser_substrate"


def _is_screenshot_step(step: Dict[str, Any]) -> bool:
    """Return True if the step is expected to produce a screenshot artifact.

    Yoke uses the executor vocabulary from ``docs/browser-scenario-schema``:
    artifact-producing screenshot steps are ``action="screenshot"`` with
    ``capture=true``. Non-capturing screenshot steps succeed without artifacts
    and must not count toward screenshot evidence completeness.
    """
    if not isinstance(step, dict):
        return False
    return step.get("action") in _SCREENSHOT_ACTIONS and bool(step.get("capture"))


def _execute_step(
    step_json: Dict[str, Any],
    base_url: str,
    artifact_dir: str,
    run_id: int,
    item_id: int,
    project: str,
    route: str,
    step_index: int,
) -> Dict[str, Any]:
    """Execute a single scenario step via ``browser_client``.

    Returns the parsed JSON response from the daemon, or an error dict.
    """
    from yoke_core.domain.browser_client import execute_step, daemon_running

    if not daemon_running():
        return {"success": False, "error": "env_setup_failure", "exit_code": 2}

    try:
        return execute_step(step_json, base_url, output_dir=artifact_dir)
    except RuntimeError as e:
        return {"success": False, "error": str(e)}


def _dispatch_qa_write(
    function_id: str,
    requirement_id: int,
    payload: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Dispatch one qa write; return the result payload or None on failure."""
    # Lazy import: the structured-API adapter sits above the domain layer
    # (same pattern as browser_qa_scenario._fetch_browser_context).
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    try:
        response = call_dispatcher(
            function_id=function_id,
            target=TargetRef(
                kind="qa_requirement", qa_requirement_id=int(requirement_id),
            ),
            payload=payload,
        )
    except Exception:
        return None
    if not response.success:
        return None
    return response.result or {}


def _record_run(
    req_id: int,
    qa_kind: str,
    verdict: Optional[str] = None,
    raw_result: Optional[str] = None,
) -> Optional[int]:
    """Record a qa_run via ``qa.run.add``. Returns the run id or None."""
    payload: Dict[str, Any] = {
        "executor_type": _BROWSER_EXECUTOR_TYPE,
        "qa_kind": qa_kind,
    }
    if verdict is not None:
        payload["verdict"] = verdict
    if raw_result is not None:
        payload["raw_result"] = raw_result
    result = _dispatch_qa_write("qa.run.add", req_id, payload)
    if result is None:
        return None
    run_id = result.get("qa_run_id")
    return int(run_id) if run_id is not None else None


def _complete_run(
    run_id: int,
    requirement_id: int,
    verdict: Optional[str] = None,
    raw_result: Optional[str] = None,
    *,
    execution_status: Optional[str] = None,
) -> None:
    """Finalize a qa_run via ``qa.run.complete``.

    For browser captures, verdict is None at capture completion
    (inspection hasn't happened yet) and execution_status='captured'.
    Capture failures pass verdict='fail' + execution_status='capture_failed'.
    Inspection later calls qa.run.complete again to set verdict alone.
    """
    payload: Dict[str, Any] = {"run_id": int(run_id)}
    if verdict is not None:
        payload["verdict"] = verdict
    if execution_status is not None:
        payload["execution_status"] = execution_status
    if raw_result is not None:
        payload["raw_result"] = raw_result
    _dispatch_qa_write("qa.run.complete", requirement_id, payload)


def _record_artifact(
    run_id: int,
    requirement_id: int,
    artifact_type: str,
    content_type: str,
    artifact_handle: Dict[str, Any],
    metadata: str,
) -> Optional[int]:
    """Record a qa_artifact via ``qa.artifact.add``. Returns the id or None."""
    result = _dispatch_qa_write(
        "qa.artifact.add",
        requirement_id,
        {
            "run_id": int(run_id),
            "artifact_type": artifact_type,
            "content_type": content_type,
            "artifact_handle": artifact_handle,
            "metadata": metadata,
        },
    )
    if result is None:
        return None
    artifact_id = result.get("qa_artifact_id")
    return int(artifact_id) if artifact_id is not None else None


def _presign_artifact(
    run_id: int,
    requirement_id: int,
    filename: str,
    content_type: str,
) -> Optional[Dict[str, Any]]:
    """Mint a presigned PUT via ``qa.artifact.presign`` (None on any miss)."""
    return _dispatch_qa_write(
        "qa.artifact.presign",
        requirement_id,
        {
            "run_id": int(run_id),
            "filename": filename,
            "content_type": content_type,
        },
    )


def _upload_artifact(upload_url: str, file_path: str, content_type: str) -> bool:
    """PUT the capture bytes to the presigned URL (plain HTTPS, no creds)."""
    import urllib.error
    import urllib.request

    try:
        with open(file_path, "rb") as fh:
            body = fh.read()
        request = urllib.request.Request(
            upload_url,
            data=body,
            method="PUT",
            headers={"Content-Type": content_type or "application/octet-stream"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _durable_artifact_handle(
    run_id: int,
    requirement_id: int,
    file_path: str,
    content_type: str,
) -> Dict[str, Any]:
    """Return the handle to record for one on-disk capture.

    Presign + upload yields the durable S3 handle; any miss yields an
    explicit ``local`` handle on the capture's absolute path.
    """
    # Lazy import keeps this module patchable per-helper in tests.
    from yoke_core.domain import browser_qa as _bqa
    from yoke_core.domain.qa_artifact_handle import local_handle

    filename = os.path.basename(str(file_path))
    presigned = _bqa._presign_artifact(
        run_id, requirement_id, filename, content_type,
    )
    if presigned:
        upload_url = presigned.get("upload_url")
        handle = presigned.get("artifact_handle")
        if (
            isinstance(upload_url, str)
            and isinstance(handle, dict)
            and _bqa._upload_artifact(upload_url, file_path, content_type)
        ):
            return handle
        _bqa._log(
            f"  upload to durable storage failed for {filename}; "
            "recording explicit local handle"
        )
    return local_handle(os.path.abspath(str(file_path)), content_type)
