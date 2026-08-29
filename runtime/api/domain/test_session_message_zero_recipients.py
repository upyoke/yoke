"""The refusal a selector that reached nobody teaches."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_message_zero_recipients import (
    ZERO_RECIPIENTS_CODE,
    require_recipients,
    zero_recipients_detail,
)

SESSION_ID = "019e41e1-9b2c-7a41-8f30-6d5a0c7b2e14"


def test_an_unresolved_session_id_names_it_and_offers_the_item_form() -> None:
    detail = zero_recipients_detail(RecipientSelector(session_ids=[SESSION_ID]))
    assert SESSION_ID in detail
    assert "yoke say --item PREFIX-N --stdin" in detail
    assert "shortened, padded, or hand-assembled" in detail


def test_an_unheld_item_says_the_item_addresses_nobody_right_now() -> None:
    detail = zero_recipients_detail(RecipientSelector(public_refs=["YOK-1"]))
    assert "YOK-1" in detail
    assert "yoke claims work holder-get PREFIX-N" in detail


def test_a_roster_audience_points_at_the_filters_that_narrowed_it() -> None:
    detail = zero_recipients_detail(RecipientSelector(universe=True))
    assert "--liveness" in detail
    assert zero_recipients_detail(RecipientSelector(projects=["yoke"])) == detail


def test_recipients_present_is_not_a_refusal() -> None:
    require_recipients([object()], RecipientSelector(public_refs=["YOK-1"]))


def test_no_recipients_raises_the_stable_code_carrying_the_detail() -> None:
    selector = RecipientSelector(session_ids=[SESSION_ID])
    with pytest.raises(SessionMessageError) as raised:
        require_recipients([], selector)
    assert raised.value.code == ZERO_RECIPIENTS_CODE
    assert SESSION_ID in str(raised.value)
