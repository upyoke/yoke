"""PNG evidence shared by desktop captures and authority-side submissions."""

from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES


def screenshot_png(encoded: str) -> tuple[bytes, tuple[int, int]]:
    """Decode a bounded, nonblank PNG or refuse unusable desktop evidence."""
    if len(encoded) > (MAX_ARTIFACT_BYTES * 4 // 3 + 4):
        raise ValueError(
            "screenshot_png_too_large: reduce the desktop resolution and retry"
        )
    try:
        content = base64.b64decode(encoded, validate=True)
        if not content or len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError("invalid size")
        with Image.open(BytesIO(content)) as image:
            if image.format != "PNG" or image.width < 2 or image.height < 2:
                raise ValueError("not a desktop PNG")
            image.load()
            if all(low == high for low, high in image.convert("RGB").getextrema()):
                raise ValueError("blank desktop")
            size = image.size
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError(
            "screenshot_png_invalid: unlock the dedicated test desktop, verify its "
            "display and capture permissions, then retry"
        ) from exc
    return content, size
