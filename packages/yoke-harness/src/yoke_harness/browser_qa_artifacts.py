"""Artifact scratch paths and QA write delegates for product browser QA."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.error
import urllib.request

from yoke_cli.config import machine_config
from yoke_contracts.api.function_call import TargetRef
from yoke_harness.browser_qa_results import (
    BROWSER_EXECUTOR_TYPE,
    Dispatcher,
    QA_ARTIFACT_STORAGE_KIND,
    RUN_ENV_KEYS,
    SCRATCH_ROOT_ENV,
    SESSION_ENV_KEYS,
    log,
)


def dispatch_qa_write(
    dispatcher: Dispatcher,
    function_id: str,
    requirement_id: int,
    payload: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    try:
        response = dispatcher(
            function_id,
            TargetRef(kind="qa_requirement", qa_requirement_id=int(requirement_id)),
            payload,
        )
    except Exception:
        return None
    if not response.success:
        return None
    return response.result or {}


def record_run(
    dispatcher: Dispatcher,
    req_id: int,
    qa_kind: str,
    verdict: Optional[str] = None,
    raw_result: Optional[str] = None,
) -> Optional[int]:
    payload: Dict[str, Any] = {
        "executor_type": BROWSER_EXECUTOR_TYPE,
        "qa_kind": qa_kind,
    }
    if verdict is not None:
        payload["verdict"] = verdict
    if raw_result is not None:
        payload["raw_result"] = raw_result
    result = dispatch_qa_write(dispatcher, "qa.run.add", req_id, payload)
    run_id = None if result is None else result.get("qa_run_id")
    return int(run_id) if run_id is not None else None


def complete_run(
    dispatcher: Dispatcher,
    run_id: int,
    requirement_id: int,
    verdict: Optional[str] = None,
    raw_result: Optional[str] = None,
    *,
    execution_status: Optional[str] = None,
) -> None:
    payload: Dict[str, Any] = {"run_id": int(run_id)}
    if verdict is not None:
        payload["verdict"] = verdict
    if execution_status is not None:
        payload["execution_status"] = execution_status
    if raw_result is not None:
        payload["raw_result"] = raw_result
    dispatch_qa_write(dispatcher, "qa.run.complete", requirement_id, payload)


def record_artifact(
    dispatcher: Dispatcher,
    run_id: int,
    requirement_id: int,
    artifact_type: str,
    content_type: str,
    artifact_handle: Dict[str, Any],
    metadata: str,
) -> Optional[int]:
    result = dispatch_qa_write(
        dispatcher,
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
    artifact_id = None if result is None else result.get("qa_artifact_id")
    return int(artifact_id) if artifact_id is not None else None


def durable_artifact_handle(
    dispatcher: Dispatcher,
    run_id: int,
    requirement_id: int,
    file_path: str,
    content_type: str,
) -> Dict[str, Any]:
    filename = os.path.basename(str(file_path))
    presigned = presign_artifact(
        dispatcher, run_id, requirement_id, filename, content_type,
    )
    if presigned:
        upload_url = presigned.get("upload_url")
        handle = presigned.get("artifact_handle")
        if (
            isinstance(upload_url, str)
            and isinstance(handle, dict)
            and upload_artifact(upload_url, file_path, content_type)
        ):
            return handle
        log(f"upload to durable storage failed for {filename}; recording local handle")
    return local_handle(os.path.abspath(str(file_path)), content_type)


def presign_artifact(
    dispatcher: Dispatcher,
    run_id: int,
    requirement_id: int,
    filename: str,
    content_type: str,
) -> Optional[Dict[str, Any]]:
    return dispatch_qa_write(
        dispatcher,
        "qa.artifact.presign",
        requirement_id,
        {"run_id": int(run_id), "filename": filename, "content_type": content_type},
    )


def upload_artifact(upload_url: str, file_path: str, content_type: str) -> bool:
    try:
        with open(file_path, "rb") as file_handle:
            body = file_handle.read()
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


def artifact_directory(project: str, item_id: int, run_id: int) -> Path:
    path = scratch_root(project) / "storage" / QA_ARTIFACT_STORAGE_KIND
    path = path / safe_segment(str(item_id)) / safe_segment(str(run_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_metadata(
    step_index: int,
    qa_kind: str,
    item_id: int,
    route: str = "/",
) -> Dict[str, Any]:
    return {
        "step_index": step_index,
        "qa_kind": qa_kind,
        "item_id": item_id,
        "route": route,
        "browser": "chromium",
    }


def local_handle(path: str, content_type: Optional[str] = None) -> Dict[str, Any]:
    handle: Dict[str, Any] = {"backend": "local", "path": str(path)}
    if content_type:
        handle["content_type"] = str(content_type)
    return handle


def scratch_root(project: str) -> Path:
    root = global_scratch_root() / safe_segment(project)
    root = root / "sessions" / session_segment() / "runs" / run_segment()
    root.mkdir(parents=True, exist_ok=True)
    return root


def global_scratch_root() -> Path:
    override = os.environ.get(SCRATCH_ROOT_ENV, "").strip()
    if override:
        return absolute_machine_path(override)
    try:
        configured = machine_config.temp_root()
    except Exception:
        configured = ""
    if configured:
        return absolute_machine_path(configured)
    return Path(tempfile.gettempdir()) / "yoke-scratch"


def absolute_machine_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return machine_config.yoke_home() / path


def session_segment() -> str:
    for key in SESSION_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return safe_segment(value)
    return "session-unknown"


def run_segment() -> str:
    for key in RUN_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return safe_segment(value)
    return safe_segment(f"pid-{os.getpid()}")


def safe_segment(value: str) -> str:
    text = str(value).strip()
    if not text or text in {".", ".."}:
        raise ValueError("scratch path segment must be non-empty")
    path = Path(text)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError(f"unsafe scratch path segment: {value!r}")
    return text


__all__ = [
    "artifact_directory",
    "build_metadata",
    "complete_run",
    "durable_artifact_handle",
    "record_artifact",
    "record_run",
]
