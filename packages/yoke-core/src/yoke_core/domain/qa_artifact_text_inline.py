"""Inline the bytes of a small text artifact held in S3.

A browser reading QA evidence cannot fetch a text object from the artifact
bucket itself: the bucket serves no CORS headers, so a presigned URL works
for an ``<img>`` but not for reading a command's recorded output as text.
The server reads a bounded text object through the same presigned URL and
returns its bytes inline, the shape local evidence already uses.
"""

from __future__ import annotations

import base64
import urllib.request
from typing import Optional

#: Recorded command output is a tail, not a log archive; anything larger
#: stays behind its download URL.
MAX_INLINE_TEXT_BYTES = 256 * 1024
FETCH_TIMEOUT_S = 10


def is_text_content(content_type: Optional[str]) -> bool:
    return str(content_type or "").split(";")[0].strip().startswith("text/")


def inline_text_base64(download_url: str) -> Optional[str]:
    """Base64 of the object at ``download_url``, or None when unreadable or too large."""
    try:
        with urllib.request.urlopen(download_url, timeout=FETCH_TIMEOUT_S) as response:
            data = response.read(MAX_INLINE_TEXT_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_INLINE_TEXT_BYTES:
        return None
    return base64.b64encode(data).decode("ascii")
