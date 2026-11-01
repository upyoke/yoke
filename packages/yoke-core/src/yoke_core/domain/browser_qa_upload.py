"""Bound browser capture uploads before sending bytes to object storage."""

from yoke_core.domain.browser_qa_steps import QaArtifactWriteError


def _upload_artifact(upload_url: str, file_path: str, content_type: str) -> None:
    """PUT capture bytes; retain the actual failure for the QA run."""
    import os
    from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES

    import urllib.error
    import urllib.request

    try:
        with open(file_path, "rb") as fh:
            if os.fstat(fh.fileno()).st_size > MAX_ARTIFACT_BYTES:
                raise QaArtifactWriteError(
                    f"artifact_too_large: capture exceeds {MAX_ARTIFACT_BYTES} bytes; "
                    "capture a smaller region and retry"
                )
            body = fh.read(MAX_ARTIFACT_BYTES + 1)
            if len(body) > MAX_ARTIFACT_BYTES:
                raise QaArtifactWriteError(
                    "artifact_too_large: capture grew during upload; "
                    "capture a smaller region and retry"
                )
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


