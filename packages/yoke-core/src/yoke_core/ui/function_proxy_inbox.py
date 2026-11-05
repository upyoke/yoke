"""Inbox browser functions use the proxy's resolved actor identity."""

INBOX_READ_FUNCTIONS = frozenset(
    {"inbox.list", "decision_requests.attachment.read", "audiences.list"}
)
INBOX_MUTATION_FUNCTIONS = frozenset({"decision_requests.resolve", "inbox.posts.done"})
INBOX_ACTOR_READ_FUNCTIONS = frozenset({"inbox.list", "audiences.list"})
