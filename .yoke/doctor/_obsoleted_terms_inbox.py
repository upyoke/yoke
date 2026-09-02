"""Retired Inbox notification substrate and the nonblocking review kind.

The Inbox once carried four panels. Two of them -- nonblocking requests and
addressed event notifications -- were filled by producers no operator ever
acted on, so the delivery table, its three notification kinds, the strategy
revision review kind, the mark-read controls, and the ``blocking`` flag that
distinguished a gate from a request were all retired together. An agent that
needs the operator to know something sends a message instead.

``ItemBlocked`` / ``ItemUnblocked`` / ``InboxNotificationRead`` were emitted
only to feed those deliveries and are retired with them. The deployment-run
and decision-request events are NOT here: the pipeline and the decision
lifecycle still read them.
"""

from __future__ import annotations

_RETIRED_DELIVERY_TABLE = r"addressed" + r"_event_deliveries"
_RETIRED_NOTIFICATION_MODULE = r"\binbox" + r"_notifications\b"
_RETIRED_NOTIFICATION_DISPATCH = (
    r"\b(dispatch_addressed_event|addressed_actor_ids_for_event"
    r"|fan_out_in_app_notification|notification_rows"
    r"|mark_notification_read|mark_all_notifications_read"
    r"|IN_APP_NOTIFICATION_KINDS)\b"
)
_RETIRED_NOTIFICATION_KIND = (
    r"\b(decision" + r"_request_resolved|deployment" + r"_run_completed"
    r"|item" + r"_block_state_changed)\b"
)
_RETIRED_NOTIFICATION_READ_FUNCTION = r"\bnotifications\.read(_all)?\b"
_RETIRED_NOTIFICATION_READ_EVENT = r"\bInbox" + r"NotificationRead\b"
_RETIRED_ITEM_BLOCK_EVENT = r"\b(Item" + r"Blocked|Item" + r"Unblocked)\b"
_RETIRED_ITEM_BLOCK_MODULE = r"\bitem" + r"_block_notifications\b"
_RETIRED_NOTIFICATION_PRESENTATION = r"\b(notificationPresentation|notificationHref)\b"
_RETIRED_STRATEGY_REVIEW_KIND = r"\bstrategy" + r"_revision_review\b"
_RETIRED_STRATEGY_REVIEW_MODULE = r"\bstrategy" + r"_review_requests\b"
_RETIRED_STRATEGY_REVIEW_FUNCTION = (
    r"\b(ensure_strategy_revision_review|ensure_current_strategy_revision_review"
    r"|withdraw_superseded_strategy_reviews)\b"
)
#: Tight enough that a QA requirement's own ``blocking_mode`` column and the
#: directional ``blocking_item_id`` dependency field do not trigger: the retired
#: flag only ever appeared on a line naming the request table.
_RETIRED_DECISION_BLOCKING_COLUMN = (
    r"decision_requests\b[^\n]*[\s,(]" + "blocking" + r"\b"
)

INBOX_RETIREMENT_PATTERNS: tuple[str, ...] = (
    _RETIRED_DELIVERY_TABLE,
    _RETIRED_NOTIFICATION_MODULE,
    _RETIRED_NOTIFICATION_DISPATCH,
    _RETIRED_NOTIFICATION_KIND,
    _RETIRED_NOTIFICATION_READ_FUNCTION,
    _RETIRED_NOTIFICATION_READ_EVENT,
    _RETIRED_ITEM_BLOCK_EVENT,
    _RETIRED_ITEM_BLOCK_MODULE,
    _RETIRED_NOTIFICATION_PRESENTATION,
    _RETIRED_STRATEGY_REVIEW_KIND,
    _RETIRED_STRATEGY_REVIEW_MODULE,
    _RETIRED_STRATEGY_REVIEW_FUNCTION,
    _RETIRED_DECISION_BLOCKING_COLUMN,
)

INBOX_RETIREMENT_LABELS: dict[str, str] = {
    _RETIRED_DELIVERY_TABLE: (
        "addressed event deliveries table (retired — the Inbox carries gates "
        "and messages, and an agent that needs the operator sends a message)"
    ),
    _RETIRED_NOTIFICATION_MODULE: (
        "inbox notification module (retired with the delivery substrate)"
    ),
    _RETIRED_NOTIFICATION_DISPATCH: (
        "in-app notification fan-out and read helpers (retired)"
    ),
    _RETIRED_NOTIFICATION_KIND: (
        "retired in-app notification kind (no notification kinds remain)"
    ),
    _RETIRED_NOTIFICATION_READ_FUNCTION: (
        "notifications.read / notifications.read_all (retired function ids)"
    ),
    _RETIRED_NOTIFICATION_READ_EVENT: (
        "inbox notification read event (retired with the mark-read controls)"
    ),
    _RETIRED_ITEM_BLOCK_EVENT: (
        "item block-state events (retired — emitted only to feed notifications)"
    ),
    _RETIRED_ITEM_BLOCK_MODULE: (
        "item block notification module (retired with its events)"
    ),
    _RETIRED_NOTIFICATION_PRESENTATION: (
        "notification presentation helpers (retired with the Notifications panel)"
    ),
    _RETIRED_STRATEGY_REVIEW_KIND: (
        "strategy revision review decision kind (retired — a revision no longer "
        "raises a review nobody acts on)"
    ),
    _RETIRED_STRATEGY_REVIEW_MODULE: (
        "strategy review request module (retired with its decision kind)"
    ),
    _RETIRED_STRATEGY_REVIEW_FUNCTION: (
        "strategy revision review producers (retired with their decision kind)"
    ),
    _RETIRED_DECISION_BLOCKING_COLUMN: (
        "decision_requests blocking column (retired — every surviving kind "
        "gates, so a request blocks by being a request)"
    ),
}

#: Patterns the history entry that strips each surface must still name, because
#: its subject IS the retirement, plus the generated event catalog's rows.
INBOX_RETIREMENT_MIGRATION_SUBJECT_PATTERNS: tuple[str, ...] = (
    _RETIRED_DELIVERY_TABLE,
    _RETIRED_NOTIFICATION_KIND,
    _RETIRED_NOTIFICATION_READ_EVENT,
    _RETIRED_ITEM_BLOCK_EVENT,
    _RETIRED_STRATEGY_REVIEW_KIND,
    _RETIRED_DECISION_BLOCKING_COLUMN,
)

__all__ = [
    "INBOX_RETIREMENT_LABELS",
    "INBOX_RETIREMENT_MIGRATION_SUBJECT_PATTERNS",
    "INBOX_RETIREMENT_PATTERNS",
]
