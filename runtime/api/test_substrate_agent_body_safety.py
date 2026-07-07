"""Structural guard: dispatched-subagent canonical bodies must not teach
self-armed background `Bash` + `Monitor` patterns.

Subagent dispatched turns are atomic — a wake fired after the turn ends has
nowhere to deliver, leaving the subagent suspended and the parent dispatch
deadlocked. The remediation is foreground-only watcher wrappers
(``python3 -m yoke_core.tools.watch_pytest -- <args>`` etc.). This test
enforces the rule by asserting that no canonical agent body in
``runtime/agents/`` for the dispatched-subagent set contains the literal
substring ``run_in_background``.

The session-level prose at ``runtime/harness/claude/rules/session.md`` is
deliberately out of scope: that file owns the rule statement itself and
must name the forbidden shape verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.schema_api_context_seed import ROLE_TOPICS


def _dispatched_subagent_names() -> tuple[str, ...]:
    return tuple(
        role.removesuffix("_agent")
        for role in ROLE_TOPICS
        if role != "main_agent" and role.endswith("_agent")
    )


DISPATCHED_SUBAGENT_NAMES = _dispatched_subagent_names()

FORBIDDEN_SUBSTRING = "run_in_background"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("agent_name", DISPATCHED_SUBAGENT_NAMES)
def test_dispatched_subagent_body_has_no_run_in_background(agent_name: str) -> None:
    body_path = _repo_root() / "runtime" / "agents" / f"{agent_name}.md"
    assert body_path.exists(), f"missing canonical agent body: {body_path}"
    text = body_path.read_text(encoding="utf-8")
    assert FORBIDDEN_SUBSTRING not in text, (
        f"{body_path} teaches `{FORBIDDEN_SUBSTRING}` — dispatched subagent "
        "turns must use foreground watcher wrappers (see "
        "runtime/harness/claude/rules/session.md `## Tool Constraints`)."
    )
