"""Project mutable session names without freezing them into message bodies."""

from yoke_core.domain.session_display import session_display_names

NOTICE_PREFIX = "desktop-operator-wake"


def wake_notice_target(message):
    parts = str(message.get("idempotency_key") or "").split(":")
    return (
        (parts[1], parts[2]) if len(parts) == 3 and parts[0] == NOTICE_PREFIX else None
    )


def wake_notice_body(label):
    return (
        f"A message is waiting in your chat {label}. "
        "Open that chat and type anything; the next turn's hook delivers the pending message. "
        "Yoke leaves this wake to you because you control this session. "
        "The message waits until its configured expiry."
    )


def project_session_names(conn, messages):
    ids = []
    for message in messages:
        ids.append(message.get("sender_session_id"))
        ids.extend(row.get("session_id") for row in message.get("recipients", []))
        target = wake_notice_target(message)
        if target:
            ids.append(target[1])
    labels = session_display_names(conn, ids)
    for message in messages:
        sender = message.get("sender_session_id")
        if sender:
            message["sender_session_label"] = labels.get(sender, "session unavailable")
        for row in message.get("recipients", []):
            row["session_label"] = labels.get(
                row.get("session_id"), "session unavailable"
            )
        target = wake_notice_target(message)
        if target:
            message["body"] = wake_notice_body(
                labels.get(target[1], "session unavailable")
            )
