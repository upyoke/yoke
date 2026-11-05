"""Inbox and decision command registrations."""

from yoke_cli.commands.adapters import (
    audiences,
    inbox_posts,
    inbox_decisions,
    decision_request_questions,
    merge_review,
)

INBOX_DECISION_SUBCOMMAND_REGISTRY = {
    ("audiences", "create"): ("audiences.create", audiences.create),
    ("audiences", "list"): ("audiences.list", audiences.list_audiences),
    ("inbox", "posts", "create"): ("inbox.posts.create", inbox_posts.create),
    ("inbox", "posts", "done"): ("inbox.posts.done", inbox_posts.done),
    ("decision-requests", "withdraw"): (
        "decision_requests.withdraw",
        decision_request_questions.decision_requests_withdraw,
    ),
    ("decision-requests", "ask"): (
        "decision_requests.ask",
        decision_request_questions.decision_requests_ask,
    ),
    ("decision-requests", "list"): (
        "decision_requests.list",
        decision_request_questions.decision_requests_list,
    ),
    ("inbox", "list"): ("inbox.list", inbox_decisions.inbox_list),
    ("decision-requests", "get"): (
        "decision_requests.get",
        inbox_decisions.decision_requests_get,
    ),
    ("merge-review", "candidate", "evaluate"): (
        "merge_review.candidate.evaluate",
        merge_review.merge_review_candidate_evaluate,
    ),
    ("decision-requests", "resolve"): (
        "decision_requests.resolve",
        inbox_decisions.decision_requests_resolve,
    ),
    ("decision-requests", "dispose-ended"): (
        "decision_requests.dispose_ended",
        inbox_decisions.decision_requests_dispose_ended,
    ),
}
