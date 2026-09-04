"""Deliberate Fleet sends enforce message-body limits."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_message_substance import validate_body
from yoke_core.domain.session_message_types import SessionMessageError


def test_nonempty_body_is_admitted() -> None:
    validate_body("DONE ALP-1 merged as abc1234", max_body_bytes=4096)


def test_empty_and_oversized_bodies_keep_their_own_refusals() -> None:
    with pytest.raises(SessionMessageError) as empty:
        validate_body("", max_body_bytes=4096)
    assert empty.value.code == "body_empty"

    with pytest.raises(SessionMessageError) as large:
        validate_body("Escalating the blocked item now.", max_body_bytes=4)
    assert large.value.code == "body_too_large"
