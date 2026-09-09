"""Step execution and qa_run/qa_artifact recording helpers.

Owns:

- ``_SCREENSHOT_ACTIONS`` and ``_is_screenshot_step`` — vocabulary for
  artifact-producing screenshot steps (kept colocated with the predicate).
- ``_execute_step`` — single-step dispatch through the browser daemon.
- ``_record_run`` / ``_complete_run`` / ``_record_artifact`` — dispatcher
  delegates (``qa.run.add`` / ``qa.run.complete`` / ``qa.artifact.add``)
  so the writes work over both transports; failures degrade to ``None`` /
  no-op exactly as the prior in-process delegates did.
- ``_record_artifact_file`` — submit one capture durably. Configured S3 uses
  ``qa.artifact.presign`` plus a plain HTTPS PUT; genuinely unconfigured S3
  sends the bytes through ``qa.artifact.add`` for permanent server-local
  storage. Presign and upload failures stay explicit and never downgrade.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import ActorContext

_SCREENSHOT_ACTIONS = frozenset({"screenshot"})

_BROWSER_EXECUTOR_TYPE = "browser_substrate"


class QaArtifactWriteError(RuntimeError):
    """A browser capture could not reach durable evidence storage."""


def _is_screenshot_step(step: Dict[str, Any]) -> bool:
    """Return True if the step is expected to produce a screenshot artifact.

    Yoke uses the runner vocabulary from ``docs/browser-scenario-schema``:
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
    actor: Optional[ActorContext] = None,
    *,
    raise_on_failure: bool = False,
) -> Optional[Dict[str, Any]]:
    """Dispatch one qa write; return the result payload or None on failure."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.domain.qa_composed_dispatch import (
        call_qa_function,
    )

    try:
        response = call_qa_function(
            function_id=function_id,
            target=TargetRef(
                kind="qa_requirement", qa_requirement_id=int(requirement_id),
            ),
            payload=payload,
            actor=actor,
        )
    except Exception as exc:
        if raise_on_failure:
            raise QaArtifactWriteError(
                f"{function_id} transport failed: {exc}"
            ) from exc
        return None
    if not response.success:
        if raise_on_failure:
            error = response.error
            detail = (
                f"{error.code}: {error.message}"
                if error is not None
                else f"{function_id} returned an unsuccessful response"
            )
            raise QaArtifactWriteError(detail)
        return None
    return response.result or {}


def _record_run(
    req_id: int,
    qa_kind: str,
    verdict: Optional[str] = None,
    raw_result: Optional[str] = None,
    *,
    actor: Optional[ActorContext] = None,
) -> Optional[int]:
    """Record a qa_run via ``qa.run.add``. Returns the run id or None."""
    payload: Dict[str, Any] = {
        "performed_by": _BROWSER_EXECUTOR_TYPE,
        "qa_kind": qa_kind,
    }
    if verdict is not None:
        payload["verdict"] = verdict
    if raw_result is not None:
        payload["raw_result"] = raw_result
    result = _dispatch_qa_write(
        "qa.run.add", req_id, payload, actor=actor,
    )
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
    actor: Optional[ActorContext] = None,
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
    _dispatch_qa_write(
        "qa.run.complete", requirement_id, payload, actor=actor,
    )


def _record_artifact(
    run_id: int,
    requirement_id: int,
    artifact_type: str,
    content_type: str,
    artifact_handle: Dict[str, Any],
    metadata: str,
    *,
    actor: Optional[ActorContext] = None,
    raise_on_failure: bool = False,
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
        actor=actor,
        raise_on_failure=raise_on_failure,
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
    *,
    actor: Optional[ActorContext] = None,
) -> Optional[Dict[str, Any]]:
    """Mint a PUT, returning None only when S3 is genuinely unconfigured."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    try:
        response = call_qa_function(
            function_id="qa.artifact.presign",
            target=TargetRef(
                kind="qa_requirement",
                qa_requirement_id=int(requirement_id),
            ),
            payload={
                "run_id": int(run_id),
                "filename": filename,
                "content_type": content_type,
            },
            actor=actor,
        )
    except Exception as exc:
        raise QaArtifactWriteError(
            f"qa.artifact.presign transport failed: {exc}"
        ) from exc
    if response.success:
        return response.result or {}
    if response.error is not None and response.error.code == "s3_not_configured":
        return None
    error = response.error
    detail = (
        f"{error.code}: {error.message}"
        if error is not None
        else "qa.artifact.presign returned an unsuccessful response"
    )
    raise QaArtifactWriteError(detail)


def _upload_artifact(upload_url: str, file_path: str, content_type: str) -> None:
    """PUT capture bytes; retain the actual failure for the QA run."""
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
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raise QaArtifactWriteError(
            f"S3 upload failed: HTTP {exc.code} {exc.reason}"
        ) from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise QaArtifactWriteError(f"S3 upload failed: {exc}") from exc
    if not 200 <= status < 300:
        raise QaArtifactWriteError(f"S3 upload failed: HTTP {status}")


def _record_artifact_file(
    run_id: int,
    requirement_id: int,
    file_path: str,
    content_type: str,
    artifact_type: str,
    metadata: str,
    *,
    actor: Optional[ActorContext] = None,
) -> int:
    """Persist one capture before recording its readable evidence row."""
    # Lazy import keeps this module patchable per-helper in tests.
    from yoke_core.domain import browser_qa as _bqa

    filename = os.path.basename(str(file_path))
    presigned = _bqa._presign_artifact(
        run_id, requirement_id, filename, content_type,
        actor=actor,
    )
    if presigned:
        upload_url = presigned.get("upload_url")
        handle = presigned.get("artifact_handle")
        if not isinstance(upload_url, str) or not isinstance(handle, dict):
            raise QaArtifactWriteError(
                "qa.artifact.presign returned no upload_url or artifact_handle"
            )
        _bqa._upload_artifact(upload_url, file_path, content_type)
        artifact_id = _bqa._record_artifact(
            run_id,
            requirement_id,
            artifact_type,
            content_type,
            handle,
            metadata,
            actor=actor,
            raise_on_failure=True,
        )
    else:
        try:
            content = Path(file_path).read_bytes()
        except OSError as exc:
            raise QaArtifactWriteError(
                f"capture file cannot be read for submission: {exc}"
            ) from exc
        result = _dispatch_qa_write(
            "qa.artifact.add",
            requirement_id,
            {
                "run_id": int(run_id),
                "artifact_type": artifact_type,
                "content_type": content_type,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "filename": filename,
                "metadata": metadata,
            },
            actor=actor,
            raise_on_failure=True,
        )
        artifact_id = result.get("qa_artifact_id") if result is not None else None
    if artifact_id is None:
        raise QaArtifactWriteError("qa.artifact.add returned no artifact id")
    return int(artifact_id)
