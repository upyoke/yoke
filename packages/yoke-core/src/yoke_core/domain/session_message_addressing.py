"""Message-only recipient safety; shared wake resolution keeps its contract."""

from yoke_core.domain.session_message_liveness import is_bulk_evidence
from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_types import SessionMessageError


def resolve_message_recipients(conn, selector, *, sender_session_id=None, **kwargs):
    if selector.projects and (
        selector.public_refs
        or selector.epic_tasks
        or selector.process_keys
        or selector.session_ids
    ):
        raise SessionMessageError(
            "selector_invalid",
            "--project cannot be combined with --item, --epic-task, --process "
            "or --session; drop --project; the item ref already names its project",
            jsonpath="$.payload.selector.projects",
        )
    return [
        recipient
        for recipient in resolve_recipients(conn, selector, **kwargs)
        if recipient.session_id != sender_session_id
        or not is_bulk_evidence(recipient.resolution)
    ]
