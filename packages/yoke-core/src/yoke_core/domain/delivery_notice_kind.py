"""Which delivery notice a message is, read from the key that minted it.

Two delivery notices reach a person's inbox and they are different events: a
QA stage reported a result, and an item finished delivering. Both are
informational — they ask for no decision — but a reader who cannot tell them
apart reads one as the other, and a retry of the same event must not look
like the second event arriving.

The discriminator is the idempotency key each notice mints, because that key
IS the event's identity: it is what makes a retry the same notice and the
other event a different one. Classifying here, beside the two builders, keeps
the prefixes in one place rather than in every reader that wants to group
them.
"""

from __future__ import annotations

from typing import Final, Optional

#: Prefixes the two notice builders mint. Their own modules import these.
QA_RESULT_NOTICE_PREFIX: Final = "deployment-qa-stage-result:"
DELIVERY_DONE_NOTICE_PREFIX: Final = "delivery-done:"

#: What each prefix means to a reader grouping its inbox.
QA_RESULT_NOTICE_KIND: Final = "qa_result"
DELIVERY_DONE_NOTICE_KIND: Final = "delivery_done"

_PREFIX_KINDS: Final = (
    (QA_RESULT_NOTICE_PREFIX, QA_RESULT_NOTICE_KIND),
    (DELIVERY_DONE_NOTICE_PREFIX, DELIVERY_DONE_NOTICE_KIND),
)


def delivery_notice_kind(idempotency_key: Optional[str]) -> Optional[str]:
    """Return the notice kind this key names, or None for an ordinary message.

    An ordinary message between people carries no delivery-notice key, and
    answering None for it is the point: it belongs with the messages a person
    may have to answer, not with the notices that only report.
    """
    key = str(idempotency_key or "")
    for prefix, kind in _PREFIX_KINDS:
        if key.startswith(prefix):
            return kind
    return None


def classify_messages(messages: "list[dict]") -> "list[dict]":
    """Stamp each inbox message with the delivery notice it is, or None.

    The Inbox groups on this, so the grouping and the keys it reads live in
    one module: a reader that recognized notices by their wording would start
    mis-sorting the first time a notice was reworded.
    """
    return [
        {**row, "notice_kind": delivery_notice_kind(row.get("idempotency_key"))}
        for row in messages
    ]


__all__ = [
    "DELIVERY_DONE_NOTICE_KIND",
    "DELIVERY_DONE_NOTICE_PREFIX",
    "QA_RESULT_NOTICE_KIND",
    "QA_RESULT_NOTICE_PREFIX",
    "classify_messages",
    "delivery_notice_kind",
]
