"""One Yoke evaluation per native event, and machine-scope delivery in budget.

Inside a project a harness fires both its project config and its user config
(Cursor also fires an imported Claude config). The step-aside rule must leave
exactly one invocation, so the composer runs once and teaching is never
repeated. Outside a project only the user-level hook runs, and what it
delivers goes through the same composer under the same byte ceiling.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

from yoke_cli.commands.adapters.hook_config_dedup import should_skip_config_duplicate
from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS, entry_commands
from yoke_contracts.hook_context_compose import delivered_message_ids, reply_is_well_formed
from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness
from yoke_core.domain.agents_render_hooks import (
    render_claude_hooks_block,
    render_codex_hooks_block,
    render_cursor_hooks_block,
)
from yoke_core.hooks.hook_context_compose import composed_additional_context
from yoke_core.hooks.types import HookDecision, Outcome
from yoke_harness.hooks.machine_hooks_render import render_user_hook_entries

_OWNER = re.compile(r"YOKE_HOOK_CONFIG_OWNER=([\w-]+)")
_EVALUATE = re.compile(r"yoke hook evaluate (\w+)")


def _fired(harness_id: str, native_event: str, *, in_project: bool) -> list[str]:
    """Commands the harness fires for one native event."""
    configs = [render_user_hook_entries(HARNESS_MACHINE_HOOKS[harness_id])]
    if in_project:
        project = {
            "claude-code": render_claude_hooks_block,
            "codex": render_codex_hooks_block,
            "cursor": lambda: render_cursor_hooks_block()["hooks"],
        }[harness_id]()
        configs.append(project)
    fired = [
        command
        for config in configs
        for entry in config.get(native_event, [])[:1]  # one per config; matchers differ
        for command in entry_commands(entry)
    ]
    if harness_id == "cursor":
        # Cursor also fires the imported user-level ~/.claude/settings.json.
        verb = next(e.verb for e in HARNESS_MACHINE_HOOKS["cursor"].events if e.native_event == native_event)
        claude = render_user_hook_entries(HARNESS_MACHINE_HOOKS["claude-code"])
        fired += [c for entry in claude.get(verb, [])[:1] for c in entry_commands(entry)]
    return fired


def _environment(harness_id: str, root: Path, owner: str) -> dict[str, str]:
    env = {"YOKE_HOOK_CONFIG_OWNER": owner, "HOME": str(root / "home")}
    env["CURSOR_PROJECT_DIR" if harness_id == "cursor" else "CLAUDE_PROJECT_DIR"] = str(root)
    return env


def _write_project(root: Path, harness_id: str) -> None:
    if harness_id == "claude-code":
        path, doc = root / ".claude/settings.json", {"hooks": render_claude_hooks_block()}
    elif harness_id == "codex":
        path, doc = root / ".codex/hooks.json", {"hooks": render_codex_hooks_block()}
    else:
        path, doc = root / ".cursor/hooks.json", render_cursor_hooks_block()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _evaluations(harness_id: str, native_event: str, root: Path, *, in_project: bool) -> int:
    payload = {"session_id": "s-1", "cwd": str(root)}
    if harness_id == "cursor":
        payload["conversation_id"] = "s-1"  # Cursor payload provenance
        user = root / "home" / ".cursor" / "hooks.json"  # as install writes it
        user.parent.mkdir(parents=True, exist_ok=True)
        entries = render_user_hook_entries(HARNESS_MACHINE_HOOKS["cursor"])
        user.write_text(json.dumps({"version": 1, "hooks": entries}), encoding="utf-8")
    payload = json.dumps(payload)
    count = 0
    for command in _fired(harness_id, native_event, in_project=in_project):
        owner = _OWNER.search(command)
        verb = _EVALUATE.search(command).group(1)
        env = _environment(harness_id, root, owner.group(1) if owner else "")
        if not env["YOKE_HOOK_CONFIG_OWNER"]:
            del env["YOKE_HOOK_CONFIG_OWNER"]
            count += 1  # unowned project commands never consult the rule
            continue
        count += not should_skip_config_duplicate(verb, env, payload)
    return count


_CASES = [
    (harness_id, event.native_event)
    for harness_id, spec in HARNESS_MACHINE_HOOKS.items()
    for event in spec.events
]


@pytest.mark.parametrize(("harness_id", "native_event"), _CASES)
def test_exactly_one_evaluation_inside_and_outside_a_project(tmp_path, harness_id, native_event):
    outside = tmp_path / "outside"
    outside.mkdir()
    assert _evaluations(harness_id, native_event, outside, in_project=False) == 1
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project, harness_id)
    assert _evaluations(harness_id, native_event, project, in_project=True) == 1


def _delivery(index: int, body_bytes: int) -> tuple[str, str]:
    message_id = str(uuid.UUID(int=index + 1))
    block = (
        f"=== BEGIN YOKE SESSION MESSAGE DELIVERY YOKE_SESSION_MESSAGE_LEASE:lease-{index} "
        f"{message_id} ===\n"
        "Authenticated sender: steering\n"
        f"| {json.dumps('x' * body_bytes)}\n"
        "=== END YOKE SESSION MESSAGE DELIVERY ===\n\n"
        f"Acknowledge: yoke messages acknowledge {message_id}"
    )
    return message_id, block


@pytest.mark.parametrize("harness_id", sorted(HARNESS_MACHINE_HOOKS))
def test_machine_scope_delivery_stays_within_the_inline_budget(harness_id):
    messages = [_delivery(index, 1800) for index in range(4)]
    decisions = [
        HookDecision(Outcome.ALLOW, audit_fields={"additionalContext": block})
        for _, block in messages
    ]
    decisions.append(
        HookDecision(
            Outcome.ALLOW,
            audit_fields={"additionalContext": "Outside a Yoke project: machine guards only."},
        )
    )
    composed = composed_additional_context(decisions, harness_id=harness_id)
    assert len(composed.encode("utf-8")) <= inline_context_bytes_for_harness(harness_id)
    delivered = {
        match
        for token in {block.split()[6] for _, block in messages}
        for match in delivered_message_ids(composed, token)
    }
    # What fits arrives as closed blocks, whole or as a stub naming its full
    # read; the rest stays pending and redelivers on the next hook.
    assert delivered
    assert reply_is_well_formed(composed)
    assert all(message_id in composed for message_id in delivered)
