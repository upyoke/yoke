"""Read one small immutable JSON receipt from an exact workflow attempt."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from typing import Any

from yoke_core.domain.github_actions_logs import _fetch_with_retry
from yoke_core.domain.github_actions_rest import rest_get
from yoke_core.domain.gh_rest_transport import RestTransportError, github_api_base

RECEIPT_LIMIT_BYTES = 64 * 1024


class ActionsReceiptRefused(ValueError):
    """A successful run does not carry an attributable receipt."""

    def __init__(self, reason: str, detail: str):
        super().__init__(
            f"{reason}: {detail}; restore the exact attempt's receipt "
            "and re-read it; do not redispatch a completed deployment"
        )
        self.reason = reason


def read_run_receipt(
    repo: str, run: dict[str, Any], prefix: str, *, token: str
) -> dict:
    run_id = str(run["id"])
    attempt = run.get("run_attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ActionsReceiptRefused(
            "workflow_receipt_attempt_missing", "run names no attempt"
        )
    name = f"{prefix}-{run_id}-{attempt}"
    try:
        listing = rest_get(
            f"/repos/{repo}/actions/runs/{run_id}/artifacts",
            query={"name": name, "per_page": "100"},
            token=token,
        )
        artifacts = listing.get("artifacts") if isinstance(listing, dict) else None
        if not isinstance(artifacts, list) or listing.get("total_count") != len(
            artifacts
        ):
            raise ActionsReceiptRefused(
                "workflow_receipt_listing_invalid", "artifact listing is incomplete"
            )
        matches = [
            a for a in artifacts if isinstance(a, dict) and a.get("name") == name
        ]
        if len(matches) != 1:
            raise ActionsReceiptRefused(
                "workflow_receipt_missing", f"expected one artifact {name!r}"
            )
        artifact = matches[0]
        artifact_id = artifact.get("id")
        size = artifact.get("size_in_bytes")
        artifact_run = artifact.get("workflow_run")
        if (
            isinstance(artifact_id, bool)
            or not isinstance(artifact_id, int)
            or artifact_id < 1
            or artifact.get("expired") is not False
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 < size <= RECEIPT_LIMIT_BYTES
            or not isinstance(artifact_run, dict)
            or str(artifact_run.get("id")) != run_id
        ):
            raise ActionsReceiptRefused(
                "workflow_receipt_artifact_invalid",
                "artifact is expired, oversized, or from another run",
            )
        digest = str(artifact.get("digest") or "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ActionsReceiptRefused(
                "workflow_receipt_digest_missing", "artifact names no SHA256 digest"
            )
        raw = _fetch_with_retry(
            f"{github_api_base()}/repos/{repo}/actions/artifacts/{artifact_id}/zip",
            token=token,
            limit_bytes=RECEIPT_LIMIT_BYTES,
        )
        if f"sha256:{hashlib.sha256(raw).hexdigest()}" != digest:
            raise ActionsReceiptRefused(
                "workflow_receipt_digest_mismatch",
                "download differs from immutable artifact digest",
            )
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = archive.infolist()
            if (
                len(files) != 1
                or files[0].file_size > RECEIPT_LIMIT_BYTES
                or files[0].is_dir()
            ):
                raise ActionsReceiptRefused(
                    "workflow_receipt_archive_invalid",
                    "receipt must contain one small JSON file",
                )
            payload = json.loads(archive.read(files[0]))
        if not isinstance(payload, dict):
            raise ActionsReceiptRefused(
                "workflow_receipt_json_invalid", "receipt must be a JSON object"
            )
        return {
            "repository": repo,
            "run_id": run_id,
            "run_attempt": attempt,
            "run_head_sha": str(run.get("head_sha") or ""),
            "workflow_path": str(run.get("path") or "").split("@", 1)[0],
            "display_title": str(run.get("display_title") or ""),
            "artifact_id": artifact_id,
            "artifact_name": name,
            "digest": digest,
            "payload": payload,
        }
    except (
        RestTransportError,
        OSError,
        ValueError,
        zipfile.BadZipFile,
        RuntimeError,
    ) as exc:
        if isinstance(exc, ActionsReceiptRefused):
            raise
        raise ActionsReceiptRefused(
            "workflow_receipt_unreadable", "GitHub receipt could not be read or decoded"
        ) from exc
