"""A ``~`` Bash target expands against the client's home, not the evaluator's.

The guard runs on the authority. ``~`` in a redirect names the home of the
machine that will run the command, which the client reports as its
machine-home fact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from yoke_contracts.hook_runner.session_cwd import client_machine_home_fact
from yoke_core.domain.path_claim_bash_client_home import expand_client_home
from yoke_core.domain.path_claim_bash_guard import evaluate_payload
from yoke_core.domain.path_claim_bash_parser import Mutation


def _claim(worktree: Path) -> Dict:
    return {
        "id": 99,
        "owner_kind": "item",
        "owner_item_id": 1577,
        "integration_target": "main",
        "state": "active",
        "covered_paths": ("runtime/api/domain",),
        "worktree_path": str(worktree),
        "public_ref": "YOK-1577",
    }


def _payload(command: str, cwd: Path, client_home: Path | None) -> Dict:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
        "session_id": "sess-A",
    }
    if client_home is not None:
        payload.update(client_machine_home_fact(str(client_home)))
    return payload


def test_expand_client_home_rewrites_only_tilde_targets(tmp_path):
    home = tmp_path.resolve() / "client-home"
    home.mkdir()
    payload = client_machine_home_fact(str(home))
    out = expand_client_home(
        [
            Mutation(verb="redirect", target_path="~/notes/a.md"),
            Mutation(verb="rm", target_path="~"),
            Mutation(verb="rm", target_path="~other/x"),
            Mutation(verb="rm", target_path="relative/x"),
        ],
        payload,
    )
    assert [m.target_path for m in out] == [
        f"{home}/notes/a.md",
        str(home),
        "~other/x",
        "relative/x",
    ]


def test_expand_client_home_without_the_fact_is_unchanged():
    muts = [Mutation(verb="redirect", target_path="~/notes/a.md")]
    assert expand_client_home(muts, {}) == muts


def test_tilde_redirect_resolves_under_the_client_home(tmp_path, monkeypatch):
    client_home = tmp_path.resolve() / "client-home"
    worktree = client_home / "YOK-1577"
    (worktree / "runtime/api/domain").mkdir(parents=True)
    authority_home = tmp_path.resolve() / "authority-home"
    authority_home.mkdir()
    monkeypatch.setenv("HOME", str(authority_home))
    assert Path.home() == authority_home

    verdict = evaluate_payload(
        _payload(
            "echo x > ~/YOK-1577/runtime/api/domain/foo.py", worktree, client_home
        ),
        claim=_claim(worktree),
    )

    assert verdict.outcome == "allow"


def test_tilde_redirect_outside_the_claim_names_the_client_path(tmp_path, monkeypatch):
    client_home = tmp_path.resolve() / "client-home"
    worktree = client_home / "YOK-1577"
    (worktree / "runtime/api/domain").mkdir(parents=True)
    authority_home = tmp_path.resolve() / "authority-home"
    authority_home.mkdir()
    monkeypatch.setenv("HOME", str(authority_home))

    verdict = evaluate_payload(
        _payload("echo x > ~/YOK-1577/docs/oof.md", worktree, client_home),
        claim=_claim(worktree),
    )

    assert verdict.outcome == "deny"
    assert verdict.target_path.startswith(str(client_home))
    assert str(authority_home) not in verdict.narrative
