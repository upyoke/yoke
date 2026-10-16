"""Existing physical checkouts survive path persistence refusal and recovery."""

from contextlib import nullcontext
import subprocess

from runtime.api.fixtures.backlog import insert_item
from yoke_cli.commands.adapters import item_worktrees
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import _register_item_worktrees
from yoke_core.domain.item_worktrees import record_item_worktree, list_item_worktrees


def test_path_record_cli_recovers_existing_checkout(test_db, monkeypatch, tmp_path):
    item_id = 987
    branch = "checkout-recovery"
    repo, checkout = tmp_path / "repo", tmp_path / "lane"

    def git(*args):
        return subprocess.run(
            ["git", *map(str, args)], check=True, capture_output=True, text=True
        ).stdout

    git("init", "-b", "main", repo)
    (repo / "tracked.txt").write_text("initial contents\n")
    git("-C", repo, "add", ".")
    git(
        "-C",
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-m",
        "Initial fixture",
    )
    git("-C", repo, "worktree", "add", "-b", branch, checkout)
    (checkout / "tracked.txt").write_text("preserved dirty contents\n")
    (checkout / "untracked.txt").write_bytes(b"preserved untracked contents\n")
    before = {p.name: p.read_bytes() for p in checkout.iterdir() if p.is_file()}
    head = git("-C", checkout, "rev-parse", "HEAD")

    insert_item(test_db, id=item_id, workflow_id="dash", status="implementing")
    lane = record_item_worktree(
        test_db, item_id=item_id, branch=branch, path=None, lane_role="implementation"
    )
    test_db.commit()
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))
    handlers = {}

    class Registry:
        def register(self, function_id, handler, *args, **kwargs):
            handlers[function_id] = handler

    _register_item_worktrees.register(Registry())
    outcomes = []

    def dispatch(**kwargs):
        request = FunctionCallRequest(
            function=kwargs["function_id"],
            actor=ActorContext(session_id="fixture"),
            target=TargetRef(kind="item", item_id=item_id),
            payload=kwargs["payload"],
            preconditions=kwargs.get("preconditions", {}),
        )
        outcome = handlers[request.function](request)
        outcomes.append(outcome)
        return 0 if outcome.primary_success else 1

    monkeypatch.setattr(item_worktrees, "dispatch_and_emit", dispatch)
    args = [
        f"YOK-{item_id}",
        "--worktree-id",
        str(lane["id"]),
        "--branch",
        branch,
        "--path",
    ]
    assert item_worktrees.item_worktrees_path_record([*args, "relative/lane"]) == 1
    assert outcomes[-1].error.code == "path_record_refused"
    assert list_item_worktrees(test_db, item_id)[0]["path"] is None
    assert {p.name: p.read_bytes() for p in checkout.iterdir() if p.is_file()} == before

    for _ in range(2):
        assert item_worktrees.item_worktrees_path_record([*args, str(checkout)]) == 0
        assert outcomes[-1].result_payload["worktree"]["id"] == lane["id"]
        assert item_worktrees.item_worktrees_list([f"YOK-{item_id}"]) == 0
        assert outcomes[-1].result_payload["worktrees"][0]["path"] == str(checkout)
    assert len(list_item_worktrees(test_db, item_id)) == 1
    assert git("-C", checkout, "rev-parse", "HEAD") == head
    assert git("-C", checkout, "branch", "--show-current").strip() == branch
    assert {p.name: p.read_bytes() for p in checkout.iterdir() if p.is_file()} == before
