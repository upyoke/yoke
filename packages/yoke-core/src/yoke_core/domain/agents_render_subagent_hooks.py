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
  ``hooks`` YAML block with exactly one matcherless command per emitted
  event: PreToolUse (runner selects the chain from ``tool_name``),
  PostToolUse observe, and SubagentStop.

Single source of truth for subagent hook chains:

All canonical role specs leave hook composition to this module. PreToolUse,
PostToolUse and PostToolUseFailure use ``yoke hook evaluate`` with role and
configuration-owner identity. The shared registry owns chain selection and
transport. Product Manager and Product Designer keep their non-Bash grants;
that grant does not change hook transport. SubagentStop remains a machine-local
auto-commit safety net with best-effort telemetry.

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
_SUBAGENT_STOP_MODULE = "python3 -m yoke_core.domain.agent_stop"


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
    return f"{CONFIG_OWNER_ENV_VAR}={CLAUDE_CONFIG_OWNER} YOKE_HOOK_AGENT_TYPE={agent}"


def _hook_entry(command: str) -> dict:
    return {"type": "command", "command": command}


def _runner_command(agent: str, event: str) -> str:
    return f"{_env_prefix(agent)} {_YOKE_HOOK_EVALUATE} {event}"


def _subagent_stop_command(agent: str) -> str:
    return f"{_env_prefix(agent)} {_SUBAGENT_STOP_MODULE}"


def render_claude_subagent_hooks_block(agent: str) -> dict:
    """Compose the per-subagent Claude ``hooks`` frontmatter block.

    Args:
        agent: Bare role name (``engineer``, ``tester``, ``architect``,
            ``boss``, ``simulator``, ``product-manager``, ``product-designer``).
            Hyphenated names are preserved verbatim — telemetry uses
            ``--agent-type product-manager`` today.

    Returns the dict-shaped ``hooks`` block ready for YAML serialisation
    as the frontmatter ``hooks`` key.

    Every role uses the same composer; tool grants do not select database
    authority or a separate telemetry launcher.
    """
    # Matcherless: the runner selects the chain from tool_name. Per-tool
    # matchers here would skip Grep/Glob and any tool the grant later adds.
    block: dict[str, list[dict]] = {}
    block["PreToolUse"] = [
        {"hooks": [_hook_entry(_runner_command(agent, "PreToolUse"))]}
    ]

    block["PostToolUse"] = [
        {"hooks": [_hook_entry(_runner_command(agent, "PostToolUse"))]}
    ]
    block["PostToolUseFailure"] = [
        {"hooks": [_hook_entry(_runner_command(agent, "PostToolUseFailure"))]}
    ]
    block["SubagentStop"] = [{"hooks": [_hook_entry(_subagent_stop_command(agent))]}]
    return block


# ---------------------------------------------------------------------------
# Canonical body + spec readers
# ---------------------------------------------------------------------------


def load_canonical(agent: str, *, target_root: Optional[Path] = None) -> str:
    """Read ``runtime/agents/<role>.md`` (canonical body text)."""
    root = require_reader_root(target_root)
    return (root / CANONICAL_DIR / f"{agent}.md").read_text(encoding="utf-8")


def load_claude_spec(agent: str, *, target_root: Optional[Path] = None) -> dict:
    """Read ``runtime/agents/<role>.claude.json`` and inject the hooks block.

    All roles receive the shared transport-aware hooks block. Canonical role
    specs carry tool grants and model settings rather than hook commands.
    """
    root = require_reader_root(target_root)
    raw = json.loads(
        (root / CANONICAL_DIR / f"{agent}.claude.json").read_text(encoding="utf-8")
    )
    ordered: dict = {}
    for key in CLAUDE_SPEC_KEY_ORDER:
        if key == "hooks":
            continue
        if key in raw:
            ordered[key] = raw[key]
    ordered["hooks"] = render_claude_subagent_hooks_block(agent)
    return ordered


def render_claude_agent(agent: str, *, target_root: Optional[Path] = None) -> str:
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
