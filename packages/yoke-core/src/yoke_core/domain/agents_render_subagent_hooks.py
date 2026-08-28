"""Per-subagent Claude rendering — adapter spec, body, and hooks block.

Owns every per-subagent rendering helper that the universal substrate
orchestrator (:mod:`yoke_core.domain.agents_render`) used to inline:

- :func:`load_canonical` — read the canonical agent body
  (``runtime/agents/<role>.md``).
- :func:`load_claude_spec` — read the canonical Claude spec
  (``runtime/agents/<role>.claude.json``) and inject a composed
  ``hooks`` block for Bash-capable subagents.
- :func:`render_claude_agent` — produce the full rendered Claude
  adapter file (frontmatter + body) for a single agent.
- :func:`render_claude_subagent_hooks_block` — compose the per-subagent
  ``hooks`` YAML block: matcherless PreToolUse (runner selects the chain
  from ``tool_name``), PostToolUse observe, and SubagentStop.

Single source of truth for subagent hook chains:

The 6 Bash-capable canonical specs
(``runtime/agents/{architect,boss,engineer,qa-walker,simulator,tester}.claude.json``)
drop their hand-authored ``hooks`` block; the composer here writes the full
block from the universal ``HOOK_ORDERING`` registry. Each PreToolUse entry
emits one runner command of the form
``YOKE_HOOK_AGENT_TYPE=<role> yoke hook evaluate PreToolUse``
  (bare shell-builtin env prefix; Claude executes hooks through a shell).
``yoke_core.domain.lint_subagent_background`` (already wired into the
Bash / Monitor / ScheduleWakeup / TaskOutput chains in
:mod:`yoke_contracts.hook_runner.hook_ordering`) reads the
``YOKE_HOOK_AGENT_TYPE`` env var at runtime to detect subagent context —
no per-chain ``--agent-type`` CLI injection is needed.

Product Designer / Product Manager are non-Bash agents
(``Read, Grep, Glob`` tool grant only) and retain their hand-authored
``hooks`` block in ``<role>.claude.json``. They never invoke the composer.
The discriminator is :func:`is_bash_capable_subagent`.

Imports from :mod:`yoke_core.domain.agents_render` would create a cycle;
this module's only Yoke dependencies are the conditional renderer, the
canonical-context expander, and the workspace resolver. Higher-level orchestration (writers, drift detection) stays in
``agents_render.py`` and re-exports the names here for backwards
compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import yaml

from yoke_core.domain.agents_render_conditional import (
    CLAUDE_HARNESS_ID,
)
from yoke_core.domain.agents_render_references import render_agent_prompt_body
from yoke_core.domain.agents_render_workspace import require_reader_root
from yoke_contracts.hook_runner.config_owner import (
    CLAUDE_CONFIG_OWNER,
    CONFIG_OWNER_ENV_VAR,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANONICAL_DIR = Path("runtime") / "agents"

# Key order for the YAML frontmatter in Claude adapter files. ``hooks`` stays
# last so the composed block reads naturally after identity-and-capability
# fields.
CLAUDE_SPEC_KEY_ORDER = [
    "name",
    "description",
    "tools",
    "disallowedTools",
    "model",
    "maxTurns",
    "permissionMode",
    "hooks",
]


# ---------------------------------------------------------------------------
# Subagent hook block composition
# ---------------------------------------------------------------------------

_YOKE_HOOK_EVALUATE = "yoke hook evaluate"
_OBSERVE_MODULE = "python3 -m yoke_core.domain.observe"
_SUBAGENT_STOP_MODULE = "python3 -m yoke_core.domain.agent_stop"

def _granted_tools(tools: str) -> set[str]:
    return {part.strip() for part in tools.split(",") if part.strip()}


def is_bash_capable_subagent(tools: str) -> bool:
    """Return True when the agent's tool grant includes ``Bash``."""
    return "Bash" in _granted_tools(tools)


def _env_prefix(agent: str) -> str:
    """Return a shell-builtin env-prefix that sets ``YOKE_HOOK_AGENT_TYPE``.

    Claude executes hook commands through a shell, so the bare
    ``VAR=value cmd`` form (no ``env`` binary) is equivalent to
    ``env VAR=value cmd`` and stays compatible with
    :func:`yoke_project_checks.check_agents_hooks._classify_hook_command`,
    which strips leading ``VAR=value`` assignments before classifying the
    executable. Routing through the ``env`` binary instead would force the
    classifier to special-case ``env`` to find the real executable.
    """
    return (
        f"{CONFIG_OWNER_ENV_VAR}={CLAUDE_CONFIG_OWNER} "
        f"YOKE_HOOK_AGENT_TYPE={agent}"
    )


def _hook_entry(command: str) -> dict:
    return {"type": "command", "command": command}


def _runner_command(agent: str, event: str) -> str:
    return f"{_env_prefix(agent)} {_YOKE_HOOK_EVALUATE} {event}"


def _observe_command(agent: str, hook_event: str) -> str:
    body = (
        f'{_OBSERVE_MODULE} --project-dir "${{CLAUDE_PROJECT_DIR:-$PWD}}" '
        f"--agent-type {agent} --hook-event {hook_event}"
    )
    return f"{_env_prefix(agent)} {body}"


def _subagent_stop_command(agent: str) -> str:
    return f"{_env_prefix(agent)} {_SUBAGENT_STOP_MODULE}"


def render_claude_subagent_hooks_block(
    agent: str, *, tools: str
) -> Optional[dict]:
    """Compose the per-subagent Claude ``hooks`` frontmatter block.

    Args:
        agent: Bare role name (``engineer``, ``tester``, ``architect``,
            ``boss``, ``simulator``, ``product-manager``, ``product-designer``).
            Hyphenated names are preserved verbatim — telemetry uses
            ``--agent-type product-manager`` today.
        tools: Comma-separated tool grant string from
            ``<role>.claude.json``.

    Returns the dict-shaped ``hooks`` block ready for YAML serialisation
    as the frontmatter ``hooks`` key.

    Caller-side dispatch (``load_claude_spec`` below) uses
    :func:`is_bash_capable_subagent` to decide whether to invoke this
    composer or fall back to the canonical JSON's hand-authored block
    (PM/PD remain hand-authored).
    """
    # Matcherless: the runner selects the chain from tool_name. Per-tool
    # matchers here would skip Grep/Glob and any tool the grant later adds.
    _ = tools
    block: dict[str, list[dict]] = {}
    block["PreToolUse"] = [
        {"hooks": [_hook_entry(_runner_command(agent, "PreToolUse"))]}
    ]

    block["PostToolUse"] = [
        {"hooks": [_hook_entry(_observe_command(agent, "PostToolUse"))]}
    ]
    block["PostToolUseFailure"] = [
        {"hooks": [_hook_entry(_observe_command(agent, "PostToolUseFailure"))]}
    ]
    block["SubagentStop"] = [
        {"hooks": [_hook_entry(_subagent_stop_command(agent))]}
    ]
    return block


# ---------------------------------------------------------------------------
# Canonical body + spec readers
# ---------------------------------------------------------------------------


def load_canonical(agent: str, *, target_root: Optional[Path] = None) -> str:
    """Read ``runtime/agents/<role>.md`` (canonical body text)."""
    root = require_reader_root(target_root)
    return (root / CANONICAL_DIR / f"{agent}.md").read_text(encoding="utf-8")


def load_claude_spec(
    agent: str, *, target_root: Optional[Path] = None
) -> dict:
    """Read ``runtime/agents/<role>.claude.json`` and inject the hooks block.

    For Bash-capable subagents (6 of 8), the canonical JSON has no
    ``hooks`` key — the composed block is injected via
    :func:`render_claude_subagent_hooks_block`. For PM/PD the canonical
    JSON's hand-authored ``hooks`` block is preserved verbatim.
    """
    root = require_reader_root(target_root)
    raw = json.loads(
        (root / CANONICAL_DIR / f"{agent}.claude.json").read_text(
            encoding="utf-8"
        )
    )
    ordered: dict = {}
    for key in CLAUDE_SPEC_KEY_ORDER:
        if key == "hooks":
            continue
        if key in raw:
            ordered[key] = raw[key]
    tools_value = raw.get("tools", "")
    if is_bash_capable_subagent(tools_value):
        ordered["hooks"] = render_claude_subagent_hooks_block(
            agent, tools=tools_value
        )
    elif "hooks" in raw:
        ordered["hooks"] = raw["hooks"]
    return ordered


def render_claude_agent(
    agent: str, *, target_root: Optional[Path] = None
) -> str:
    """Render the full Claude adapter (.md) for ``agent``."""
    spec = load_claude_spec(agent, target_root=target_root)
    root = require_reader_root(target_root)
    body = render_agent_prompt_body(
        root / CANONICAL_DIR, agent, harness_id=CLAUDE_HARNESS_ID
    ).lstrip("\n")
    frontmatter = yaml.safe_dump(
        spec,
        sort_keys=False,
        default_flow_style=False,
        width=10000,
        allow_unicode=True,
    )
    return f"---\n{frontmatter}---\n\n{body}"
