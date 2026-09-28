"""Server-side inlining of small text artifacts read from S3."""

from __future__ import annotations

import base64
import io
from unittest.mock import patch

from yoke_core.domain import qa_artifact_text_inline as inline


def test_text_content_types_are_recognised() -> None:
    assert inline.is_text_content("text/plain")
    assert inline.is_text_content("text/plain; charset=utf-8")
    assert not inline.is_text_content("image/png")
    assert not inline.is_text_content(None)


def test_small_text_object_is_returned_as_base64() -> None:
    with patch.object(inline.urllib.request, "urlopen", return_value=io.BytesIO(b"ok\n")):
        assert inline.inline_text_base64("https://bucket/key") == base64.b64encode(b"ok\n").decode()


def test_oversized_or_unreadable_object_stays_behind_its_url() -> None:
    big = io.BytesIO(b"x" * (inline.MAX_INLINE_TEXT_BYTES + 1))
    with patch.object(inline.urllib.request, "urlopen", return_value=big):
        assert inline.inline_text_base64("https://bucket/key") is None
    with patch.object(inline.urllib.request, "urlopen", side_effect=OSError("403")):
        assert inline.inline_text_base64("https://bucket/key") is None
