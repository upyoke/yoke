"""Every harness adapter inherits parent tools and permissions for every role."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib

import pytest
import yaml

from yoke_core.domain.agents_render import AGENTS
from yoke_core.domain.agents_render_codex import render_codex_agent
from yoke_core.domain.agents_render_cursor import render_cursor_agent
from yoke_core.domain.agents_render_subagent_hooks import render_claude_agent

RESTRICTIONS = {"tools", "disallowedTools", "sandbox_mode", "readonly"}


@pytest.mark.parametrize("role", AGENTS)
@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
def test_agent_inherits_parent_capabilities(role: str, harness: str) -> None:
    root = Path(__file__).resolve().parents[3]
    canonical = root / "runtime" / "agents"
    spec = json.loads((canonical / f"{role}.{harness}.json").read_text())
    assert not RESTRICTIONS.intersection(spec)
    if harness == "codex":
        rendered = render_codex_agent(canonical, role)
        metadata = tomllib.loads(rendered)
    else:
        rendered = (
            render_claude_agent(role, target_root=root)
            if harness == "claude"
            else render_cursor_agent(canonical, role)
        )
        metadata = yaml.safe_load(rendered.split("---", 2)[1])
    assert not RESTRICTIONS.intersection(metadata)
