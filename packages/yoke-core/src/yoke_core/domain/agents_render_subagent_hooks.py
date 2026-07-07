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
  ``hooks`` YAML block by walking
  :data:`yoke_contracts.hook_runner.hook_ordering.HOOK_ORDERING`.

Single source of truth for subagent hook chains:

The 5 Bash-capable canonical specs
(``runtime/agents/{architect,boss,engineer,simulator,tester}.claude.json``)
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
canonical-context expander, the workspace resolver, and the universal hook
ordering. Higher-level orchestration (writers, drift detection) stays in
``agents_render.py`` and re-exports the names here for backwards
compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

import yaml

from yoke_core.domain.agents_render_conditional import (
    CLAUDE_HARNESS_ID,
    apply_conditional_blocks,
)
from yoke_core.domain.agents_render_context import expand_markers
from yoke_core.domain.agents_render_field_note import (
    expand_field_note_markers,
)
from yoke_core.domain.agents_render_workspace import require_reader_root
from yoke_contracts.hook_runner.hook_ordering import (
    matchers_for,
    ordered_pipeline_for,
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

# Claude's PreToolUse matchers: skip Codex-only ``apply_patch`` and the
# ``_default`` placeholder used by non-Pre events.
_CLAUDE_PRETOOL_OMIT: frozenset[str] = frozenset({"_default", "apply_patch"})

# Matchers whose underlying tool is only reachable when ``Bash`` is granted.
# Non-Bash agents (PM/PD) cannot reach these tools, so the entries would be
# inert noise — emit only matchers whose tool is in the agent's grant.
_BASH_ONLY_MATCHERS: frozenset[str] = frozenset(
    {"Bash", "Monitor", "ScheduleWakeup", "TaskOutput"}
)


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
    :func:`yoke_core.engines.doctor_hc_agents_hooks._classify_hook_command`,
    which strips leading ``VAR=value`` assignments before classifying the
    executable. Routing through the ``env`` binary instead would force the
    classifier to special-case ``env`` to find the real executable.
    """
    return f"YOKE_HOOK_AGENT_TYPE={agent}"


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


def _pretool_matchers_for(
    agent_tools: set[str], *, bash_capable: bool
) -> Iterable[str]:
    """Yield matchers to emit for PreToolUse, in registry order.

    Bash-capable subagents get every registered matcher whose chain is
    non-empty (full deny coverage for ``lint_subagent_background``).
    Non-Bash subagents (PM/PD) emit only matchers whose underlying tool
    is granted; the Bash-only matchers would never fire for them.
    """
    for matcher in matchers_for("PreToolUse"):
        if matcher in _CLAUDE_PRETOOL_OMIT:
            continue
        if not ordered_pipeline_for("PreToolUse", matcher):
            continue
        if not bash_capable:
            if matcher in _BASH_ONLY_MATCHERS or matcher not in agent_tools:
                continue
        yield matcher


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
    granted = _granted_tools(tools)
    bash_capable = "Bash" in granted

    block: dict[str, list[dict]] = {}

    pre_entries: list[dict] = []
    for matcher in _pretool_matchers_for(granted, bash_capable=bash_capable):
        pre_entries.append(
            {
                "matcher": matcher,
                "hooks": [_hook_entry(_runner_command(agent, "PreToolUse"))],
            }
        )
    if pre_entries:
        block["PreToolUse"] = pre_entries

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

    For Bash-capable subagents (5 of 7), the canonical JSON has no
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
    canonical = load_canonical(agent, target_root=target_root)
    body = apply_conditional_blocks(
        expand_field_note_markers(expand_markers(canonical)),
        CLAUDE_HARNESS_ID,
    ).lstrip("\n")
    frontmatter = yaml.safe_dump(
        spec,
        sort_keys=False,
        default_flow_style=False,
        width=10000,
        allow_unicode=True,
    )
    return f"---\n{frontmatter}---\n\n{body}"
