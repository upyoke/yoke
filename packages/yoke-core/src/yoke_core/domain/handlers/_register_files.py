"""Shared-file upload registration."""

from __future__ import annotations

from yoke_core.domain.handlers import files_upload as _upload


def register(registry) -> None:
    registry.register(
        "files.upload",
        _upload.handle_files_upload,
        _upload.FilesUploadRequest,
        _upload.FilesUploadResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.files_upload",
        target_kinds=["global"],
        side_effects=["shared_file_store"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
