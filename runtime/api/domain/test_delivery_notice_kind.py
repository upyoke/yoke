"""A delivery notice is classified by the key that minted it.

Two delivery notices reach a person's inbox and they are different events, so
the inbox read says which one each message is rather than leaving a reader to
recognize a body. A message between people is neither, and the read says that
by answering nothing.
"""

from __future__ import annotations

from yoke_core.domain.delivery_notice_kind import (
    DELIVERY_DONE_NOTICE_KIND,
    QA_RESULT_NOTICE_KIND,
    classify_messages,
    delivery_notice_kind,
)
from yoke_core.domain.deployment_delivery_done_notice import (
    delivery_done_idempotency_key,
)
from yoke_core.domain.deployment_qa_result_notice import qa_result_idempotency_key


def test_each_notice_key_names_its_own_event() -> None:
    assert (
        delivery_notice_kind(delivery_done_idempotency_key(51, "run-20260726-001"))
        == DELIVERY_DONE_NOTICE_KIND
    )
    assert (
        delivery_notice_kind(
            qa_result_idempotency_key("run-20260726-001", "item-qa", 51, "passed")
        )
        == QA_RESULT_NOTICE_KIND
    )
    # A run-scoped QA result is the same event kind as a member-scoped one.
    assert (
        delivery_notice_kind(
            qa_result_idempotency_key("run-20260726-001", "run-qa", None, "rejected")
        )
        == QA_RESULT_NOTICE_KIND
    )


def test_an_ordinary_message_is_not_a_notice() -> None:
    assert delivery_notice_kind(None) is None
    assert delivery_notice_kind("") is None
    assert delivery_notice_kind("steering-report:42") is None


def test_the_inbox_read_carries_the_notice_kind_of_each_message() -> None:
    classified = classify_messages(
        [
            {"message_id": "m1", "idempotency_key": None},
            {
                "message_id": "m2",
                "idempotency_key": delivery_done_idempotency_key(
                    51, "run-20260726-001"
                ),
            },
            {
                "message_id": "m3",
                "idempotency_key": qa_result_idempotency_key(
                    "run-20260726-001", "item-qa", 51, "passed"
                ),
            },
        ]
    )
    assert [row["notice_kind"] for row in classified] == [
        None,
        DELIVERY_DONE_NOTICE_KIND,
        QA_RESULT_NOTICE_KIND,
    ]
    # The original rows are left alone; the stamp travels on a copy.
    assert set(classified[0]) == {"message_id", "idempotency_key", "notice_kind"}
