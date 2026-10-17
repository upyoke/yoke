"""Live inventories the teaching prototype references but never copies.

Commands, functions and skills come from the registries that serve them,
and documents and their links from the git-tracked tree.
"""

from __future__ import annotations

import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[3]
_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)\s]*)?\)")


def live_registries() -> dict:
    """Return command forms, function ids and skill ids served right now.

    Commands are the Atlas subcommand rows plus the client-local tool-shaped
    commands, the same two sources ``yoke --help`` lists.
    """
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_USAGE
    from yoke_contracts.skill_registry import SKILLS
    from yoke_core.tools.atlas_integrity_collect import (
        collect_function_registry,
        collect_subcommand_registry,
    )

    commands = {
        row["cli_form"]: row["function_id"]
        for row in collect_subcommand_registry()["rows"]
    }
    commands.update({form: None for form in TOOL_SHAPED_USAGE})
    functions = {row["function_id"] for row in collect_function_registry()["rows"]}
    skills = {skill.id for skill in SKILLS}
    return {"commands": commands, "functions": functions, "skills": skills}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def documents(files: list[str]) -> dict:
    """Return tracked Markdown path -> resolved repository-relative link targets."""
    tracked = set(files)
    graph = {}
    for path in files:
        if not path.endswith(".md"):
            continue
        text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
        targets = []
        for raw in _LINK.findall(text):
            if "://" in raw or raw.startswith("mailto:"):
                continue
            target = _normalize(PurePosixPath(path).parent / raw)
            if target in tracked and target not in targets:
                targets.append(target)
        graph[path] = targets
    return graph


def _normalize(path: PurePosixPath) -> str:
    parts: list[str] = []
    for part in path.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def area_of(path: str, docs_graph: dict) -> str | None:
    """Return the first area whose globs include ``path``, else ``None``."""
    for area in docs_graph.get("areas", []):
        if any(fnmatch(path, glob) for glob in area["include"]) and not any(
            fnmatch(path, glob) for glob in area.get("exclude", [])
        ):
            return area["id"]
    return None
