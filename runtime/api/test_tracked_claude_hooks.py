"""Regression guard for YOK-1384: tracked Claude hook launchers must not
inject worktree-local DB paths.

The tracked hook surface (``.claude/settings.json`` and the generated
adapter files at ``.claude/agents/yoke-*.md``) used to prefix every observe / observe_pre /
lint launcher with ``YOKE_DB="${CLAUDE_PROJECT_DIR:-$PWD}/data/yoke.db"``
and pass the same worktree-local path via ``--db``. Inside a linked worktree
(``.worktrees/<branch>/``) with ``CLAUDE_PROJECT_DIR`` unset, ``$PWD``
resolves to the linked worktree, so the explicit DB path bypassed the
Python worktree-aware resolver and pointed at a stray
``.worktrees/<branch>/data/yoke.db``. Telemetry from observe,
lint_db_cmd, and lint_event_registry then landed in the stray DB and
split the events ledger (see the stray-DB reproduction tests for the
backlog/db-helper half of the fix).

The canonical Python resolver now owns DB path resolution for these
entrypoints; the launchers must stay bare. This test walks the tracked
Claude hook surface and fails loudly if the bad injection pattern is ever
reintroduced.

It deliberately lives alongside the observe / lint tests so
``python3 -m pytest runtime/api/`` catches regressions without needing the
caller to remember a bespoke suite path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_JSON = REPO_ROOT / ".claude" / "settings.json"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


# Hook commands that resolve DB paths through the Python fallback surface
# tracked Claude hook launchers (observe, observe_pre, lint_db_cmd,
# lint_event_registry). Anything in this set must NOT carry an explicit
# worktree-local DB injection.
_PYTHON_RESOLVED_MODULES = (
    "yoke_core.domain.observe",
    "yoke_core.domain.observe_pre",
    "yoke_core.domain.lint_db_cmd",
    "yoke_core.domain.lint_event_registry",
)

# Patterns that indicate a tracked command is bypassing the Python resolver
# by injecting an explicit worktree-local DB path. Keep these synchronized
# with the item body AC-2 verification pattern.
_BAD_PREFIX_PAT = re.compile(
    r"YOKE_DB\s*=\s*(?:\"|')?[^\"'\s]*yoke\.db"
)
_BAD_OBSERVE_DB_PAT = re.compile(
    r"\bruntime\.api\.domain\.(?:observe|observe_pre)\b[^|&;]*?--db\b"
)


def _iter_settings_commands(settings_path: Path) -> Iterable[str]:
    """Yield every ``command`` string reachable from the hooks tree in
    ``.claude/settings.json``.

    The file uses the canonical nested ``{hooks: [{type, command}]}``
    schema. The traversal walks arbitrary nesting so future
    additions don't silently escape the regression guard.
    """
    if not settings_path.is_file():
        return
    data = json.loads(settings_path.read_text())
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return

    stack: List[object] = list(hooks.values())
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            cmd = node.get("command")
            if isinstance(cmd, str):
                yield cmd
            for value in node.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)


# Match both quoted (command: "...") and unquoted (command: ...) YAML values.
_AGENT_COMMAND_PAT_QUOTED = re.compile(r'^\s*command:\s*"((?:[^"\\]|\\.)*)"', re.MULTILINE)
_AGENT_COMMAND_PAT_UNQUOTED = re.compile(r'^\s*command:\s+([^\s"#][^\n]*)', re.MULTILINE)


def _iter_agent_commands(agent_path: Path) -> Iterable[str]:
    """Yield every ``command:`` entry from a yoke-*.md frontmatter.

    The agent files use YAML-in-markdown frontmatter; commands may be
    double-quoted or bare (unquoted). Both forms are matched. For quoted
    values, backslash-escapes are unescaped so the returned string matches
    the literal shell invocation the hook runner will execute.
    """
    if not agent_path.is_file():
        return
    text = agent_path.read_text()
    # Collect quoted matches first
    seen_offsets: set[int] = set()
    for match in _AGENT_COMMAND_PAT_QUOTED.finditer(text):
        raw = match.group(1)
        unescaped = re.sub(r'\\(.)', r'\1', raw)
        seen_offsets.add(match.start())
        yield unescaped
    # Then unquoted matches that were not already captured as quoted
    for match in _AGENT_COMMAND_PAT_UNQUOTED.finditer(text):
        if match.start() not in seen_offsets:
            yield match.group(1).rstrip()


def _contains_python_resolved_module(command: str) -> bool:
    return any(mod in command for mod in _PYTHON_RESOLVED_MODULES)


def _violates_python_resolver_contract(command: str) -> bool:
    """Return True when *command* injects a worktree-local DB path into a
    Python-resolved hook module.

    Non-Python-resolved modules (for example ``runtime.harness.codex.codex_hooks``
    or generic ``python3 -m pytest`` calls) are ignored — those commands
    are out of scope for this guard and may legitimately pass ``--db`` for
    other reasons.
    """
    if not _contains_python_resolved_module(command):
        return False
    if _BAD_PREFIX_PAT.search(command):
        return True
    if _BAD_OBSERVE_DB_PAT.search(command):
        return True
    return False


def test_settings_json_has_no_worktree_local_db_injection() -> None:
    """AC-2 / AC-6: ``.claude/settings.json`` must not reintroduce the
    regression pattern in any observe/lint launcher."""
    assert SETTINGS_JSON.is_file(), f"Missing tracked settings.json at {SETTINGS_JSON}"
    violations: List[str] = []
    for command in _iter_settings_commands(SETTINGS_JSON):
        if _violates_python_resolver_contract(command):
            violations.append(command)
    assert not violations, (
        "Tracked Claude hook commands in .claude/settings.json inject a "
        "worktree-local data/yoke.db path. The Python hook surface "
        "(observe, observe_pre, lint_db_cmd, lint_event_registry) "
        "owns DB resolution via yoke_core.domain.db_helpers.resolve_db_path. "
        "Strip the YOKE_DB= prefix and --db argument. See YOK-1384.\n"
        f"Violations:\n" + "\n".join(f"  - {v}" for v in violations)
    )


@pytest.mark.parametrize(
    "agent_file",
    sorted(
        p.name
        for p in AGENTS_DIR.glob("yoke-*.md")
        if p.is_file()
    ),
)
def test_yoke_agent_hooks_have_no_worktree_local_db_injection(
    agent_file: str,
) -> None:
    """AC-2 / AC-6: every tracked yoke-*.md agent file must use the
    Python resolver for observe/lint launchers."""
    agent_path = AGENTS_DIR / agent_file
    violations: List[str] = []
    for command in _iter_agent_commands(agent_path):
        if _violates_python_resolver_contract(command):
            violations.append(command)
    assert not violations, (
        f"Tracked Claude hook commands in {agent_file} inject a "
        f"worktree-local data/yoke.db path. YOK-1384: strip the "
        f"YOKE_DB= prefix and --db argument from observe/observe_pre/"
        f"lint_* launchers so they resolve DB paths via the Python "
        f"db_helpers surface.\n"
        f"Violations:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_iter_settings_commands_yields_known_entries() -> None:
    """Sanity check the traversal so a refactor that silently drops
    commands from iteration does not mask a real regression. After the
    CLI cutover every settings.json hook command line collapses to
    a ``yoke hook evaluate <event>`` invocation, so the canonical sanity
    invariant is the hook CLI's presence."""
    commands = list(_iter_settings_commands(SETTINGS_JSON))
    assert any("yoke hook evaluate" in c for c in commands), (
        "_iter_settings_commands lost hook CLI entries — traversal is broken"
    )


def test_iter_agent_commands_yields_known_entries() -> None:
    """Sanity check: make sure the agent-frontmatter regex captures every
    tracked ``command: "..."`` line. The engineer agent is the canonical
    fixture. After the CLI cutover every PreToolUse chain collapses to a
    ``yoke hook evaluate <event>`` invocation, so the canonical sanity
    invariant is the hook CLI's presence plus the env-wrapped subagent
    identity.
    """
    engineer_path = AGENTS_DIR / "yoke-engineer.md"
    if not engineer_path.is_file():
        pytest.skip("yoke-engineer.md not present")
    commands = list(_iter_agent_commands(engineer_path))
    assert any("yoke hook evaluate" in c for c in commands), (
        "_iter_agent_commands lost hook CLI entries — traversal is broken"
    )
    assert any("YOKE_HOOK_AGENT_TYPE=engineer" in c for c in commands), (
        "subagent identity env wrapper missing from rendered hook commands"
    )
