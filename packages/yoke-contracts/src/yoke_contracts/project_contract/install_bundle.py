"""Shared project-install bundle constants for server and product CLI."""

from __future__ import annotations

BUNDLE_SCHEMA = 2

# One authored tree; Claude requires its own native discovery entry. Codex
# and Cursor read .agents directly and deduplicate this physical target.
SKILL_DISCOVERY_LINKS = {".claude/skills/yoke": "../../.agents/skills/yoke"}

__all__ = ["BUNDLE_SCHEMA", "SKILL_DISCOVERY_LINKS"]
