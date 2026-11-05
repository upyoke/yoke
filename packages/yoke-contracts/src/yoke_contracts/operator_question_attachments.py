"""Question attachment transport uses the shared QA artifact limits."""

from __future__ import annotations

import base64
import binascii
import mimetypes
from pathlib import Path

from yoke_contracts.qa_artifact_limits import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_MANIFEST_BYTES,
)
from yoke_contracts.refusal_recovery import compose_refusal

ATTACHMENT_HELP = (
    "Attach an image or PDF; repeat per file. Maximum 20 MiB per file, "
    "64 MiB for the encoded attachment manifest. Uses the QA evidence store."
)


def attachment_error(reason: str, detail: str) -> ValueError:
    return ValueError(
        compose_refusal(
            f"operator_question_attachment_{reason}: {detail}",
            recovery="Provide a readable image or PDF within the attachment limits, then retry ask --attach PATH.",
        )
    )


def validate_uploads(uploads):
    if not isinstance(uploads, list):
        raise attachment_error("invalid", "attachments must be a list")
    total = 0
    checked = []
    for raw in uploads:
        if not isinstance(raw, dict):
            raise attachment_error(
                "invalid", "each attachment must name its file and bytes"
            )
        filename, content_type = raw.get("filename"), raw.get("content_type")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename
        ):
            raise attachment_error("invalid", "attachment filename must be a basename")
        if not isinstance(content_type, str) or not (
            content_type.startswith("image/") or content_type == "application/pdf"
        ):
            raise attachment_error(
                "unsupported_type", f"{filename} is not an image or PDF"
            )
        encoded = raw.get("content_base64")
        if not isinstance(encoded, str):
            raise attachment_error("invalid", "attachment bytes must be base64")
        total += len(encoded)
        if total > MAX_ARTIFACT_MANIFEST_BYTES or len(encoded) > 4 * (
            (MAX_ARTIFACT_BYTES + 2) // 3
        ):
            raise attachment_error("too_large", ATTACHMENT_HELP)
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise attachment_error(
                "invalid", "attachment bytes are not valid base64"
            ) from exc
        if not content or len(content) > MAX_ARTIFACT_BYTES:
            raise attachment_error(
                "too_large", "each attachment must contain 1 byte to 20 MiB"
            )
        checked.append((filename, content_type, content))
    return checked


def upload_files(paths):
    uploads = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            size = path.stat().st_size
            if not path.is_file():
                raise attachment_error("missing_file", f"{path} is not a file")
            if size > MAX_ARTIFACT_BYTES:
                raise attachment_error("too_large", f"{path.name} exceeds 20 MiB")
            content_type = (
                mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
            if not (
                content_type.startswith("image/") or content_type == "application/pdf"
            ):
                raise attachment_error(
                    "unsupported_type", f"{path.name} is not an image or PDF"
                )
            content = path.read_bytes()
        except OSError as exc:
            raise attachment_error("missing_file", f"cannot read {path}") from exc
        uploads.append(
            {
                "filename": path.name,
                "content_type": content_type,
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    validate_uploads(uploads)
    return uploads
