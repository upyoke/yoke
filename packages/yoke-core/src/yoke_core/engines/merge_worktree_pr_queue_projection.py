"""Complete queue order, with unreadable entries kept distinct from absence."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueueMember:
    """One queued PR, mapped back to its item by head branch name."""

    pr_num: str
    head_ref: str
    state: str = ""


def parse_queue_members(
    data: Any, *, repo: str, branch: str,
) -> tuple[list[QueueMember] | None, str | None]:
    """An empty list proves a readable, complete queue with no entries."""
    def unreadable(field: str):
        return None, (
            f"queue_order_unreadable: repository {repo} field {field} is unreadable; "
            "repair: verify GitHub App Pull requests read access, then retry"
        )

    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict) or "mergeQueue" not in repository:
        return unreadable("repository.mergeQueue")
    queue = repository["mergeQueue"]
    if queue is None:
        return None, (
            f"repository {repo} reports no merge queue on {branch!r}; "
            "configure the queue ruleset before selecting the queue route"
        )
    if not isinstance(queue, dict) or not isinstance(queue.get("entries"), dict):
        return unreadable("mergeQueue.entries")
    entries = queue["entries"]
    page = entries.get("pageInfo")
    if not isinstance(page, dict) or not isinstance(page.get("hasNextPage"), bool):
        return unreadable("entries.pageInfo.hasNextPage")
    if page["hasNextPage"]:
        return None, (
            "queue_order_incomplete: more than 50 entries; "
            "retry after the queue drains below 50 entries"
        )
    nodes = entries.get("nodes")
    if not isinstance(nodes, list):
        return unreadable("entries.nodes")
    members = []
    for node in nodes:
        if not isinstance(node, dict):
            return unreadable("entries.nodes.entry")
        if not isinstance(node.get("state"), str) or not node["state"].strip():
            return unreadable("entries.nodes.state")
        pr = node.get("pullRequest")
        if not isinstance(pr, dict):
            return unreadable("entries.nodes.pullRequest")
        number = pr.get("number")
        if type(number) is not int or number <= 0:
            return unreadable("entries.nodes.pullRequest.number")
        head = pr.get("headRefName")
        if not isinstance(head, str) or not head.strip():
            return unreadable("entries.nodes.pullRequest.headRefName")
        members.append(QueueMember(str(number), head, node["state"]))
    return members, None
