"""Bootstrap helper — shared startup-read renderer for Yoke harnesses.

Extracted from the inline Python heredoc in ``bootstrap-helper.sh``.
Reads the neutral bootstrap spec and renders the common startup context for
wrapper bootstraps and compact startup hooks.

Also exposes the Yoke-owned repo-local skill discovery contract:
wrapper-only harnesses and thin docs cannot reliably guess the canonical
skill location, so this module is the single authoritative surface for
``skill-list`` and ``skill-path`` against the hidden ``.agents/skills/yoke``
tree. The resolver deliberately never falls back to home-directory paths —
``.claude/skills/yoke`` remains a compatibility symlink, but the canonical
return value is always the ``.agents/...`` path.

Can be used as a module (import functions) or invoked via CLI::

    python3 -m runtime.harness.bootstrap required-files --spec spec.json --root /repo
    python3 -m runtime.harness.bootstrap render-compact --spec spec.json --root /repo
    python3 -m runtime.harness.bootstrap render-full --spec spec.json --root /repo
    python3 -m runtime.harness.bootstrap skill-list --root /repo
    python3 -m runtime.harness.bootstrap skill-path <skill-name> --root /repo
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from runtime.harness.bootstrap_packets import append_main_agent_compact, append_main_agent_full


# Canonical repo-relative location of the Yoke skill tree. ``.claude/skills/yoke``
# remains a compatibility symlink pointing at this path, but the resolver only
# ever returns the ``.agents/...`` canonical form.
SKILLS_ROOT_REL = Path(".agents/skills/yoke")

# Name of the root router skill whose SKILL.md lives directly at SKILLS_ROOT_REL
# rather than in a named subdirectory.
ROOT_SKILL_NAME = "yoke"

CRITICAL_RUNTIME_INVARIANTS = [
    "Yoke control-plane authority is Postgres: use "
    "`python3 -m yoke_core.cli.db_router ...` or a registered "
    "`yoke <subcommand>`.",
    "Never construct DB file paths from `$PWD`, `CLAUDE_PROJECT_DIR`, "
    "or linked worktree paths; worktree-local DBs are validation surfaces "
    "only when explicit env bindings surface them.",
]


def load_spec(spec_path: Path) -> dict:
    """Load the bootstrap-spec.json file."""
    with spec_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ordered_unique(items: List[str]) -> List[str]:
    """Deduplicate a list while preserving insertion order."""
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def read_file(root: Path, rel_path: str) -> Optional[str]:
    """Read a file relative to root, returning None if missing."""
    path = root / rel_path
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def doctrine_short(root: Path) -> str:
    """Extract the short-form prompt doctrine from prompt-philosophy.md."""
    prompt_doc = read_file(root, "docs/prompt-philosophy.md")
    if not prompt_doc:
        return ""
    match = re.search(r"`(\*\*Be the giant\.\*\*.*?)`", prompt_doc)
    return match.group(1) if match else ""


def existing(root: Path, paths: List[str]) -> List[str]:
    """Filter paths to only those that exist on disk."""
    return [path for path in paths if (root / path).is_file()]


def run_command(command: str, cwd: Path) -> Tuple[int, str]:
    """Run a shell command and return (returncode, output)."""
    completed = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    output = completed.stdout.rstrip("\n")
    if completed.returncode != 0 and not output:
        output = completed.stderr.rstrip("\n")
    return completed.returncode, output


def resolve_files(
    spec: dict, extra_files: Optional[List[str]] = None
) -> Tuple[List[str], List[str]]:
    """Resolve required and recommended file lists from spec + extras."""
    extras = extra_files or []
    required = ordered_unique(extras + spec.get("required_files", []))
    recommended = ordered_unique(spec.get("recommended_files", []))
    return required, recommended


def render_required_files(spec: dict, extra_files: Optional[List[str]] = None) -> str:
    """Render the required-files list (one per line)."""
    required, _ = resolve_files(spec, extra_files)
    return "\n".join(required)


def render_compact(root: Path, spec: dict, extra_files: Optional[List[str]] = None) -> str:
    """Render compact orientation (doctrine + file list + main_agent packet)."""
    required, _ = resolve_files(spec, extra_files)
    lines: List[str] = []
    short = doctrine_short(root)
    if short:
        lines.append("Prompt Doctrine:")
        lines.append(short)
        lines.append("")
    lines.append("Critical Runtime Invariants:")
    for invariant in CRITICAL_RUNTIME_INVARIANTS:
        lines.append(f"- {invariant}")
    lines.append("")
    lines.append("Read before editing:")
    for path in existing(root, required):
        lines.append(f"- {path}")
    append_main_agent_compact(lines)
    return "\n".join(lines)


def render_full(root: Path, spec: dict, extra_files: Optional[List[str]] = None) -> str:
    """Render full orientation (file contents + command outputs + recommended)."""
    required, recommended = resolve_files(spec, extra_files)
    required_commands = spec.get("required_commands", [])
    parts: List[str] = []

    parts.append("=== Critical Runtime Invariants ===")
    parts.extend(f"- {invariant}" for invariant in CRITICAL_RUNTIME_INVARIANTS)
    parts.append("")
    append_main_agent_full(parts)

    for rel_path in required:
        content = read_file(root, rel_path)
        if content is None:
            print(f"[WARN] Missing: {root / rel_path}", file=sys.stderr)
            continue
        parts.append(f"=== {rel_path} ===")
        parts.append(content.rstrip("\n"))
        parts.append("")

    for command_def in required_commands:
        label = command_def.get("label", "Command")
        command = command_def.get("command", "")
        parts.append(f"=== {label} ===")
        if not command:
            print(f"[WARN] Missing command definition", file=sys.stderr)
            parts.append("")
            continue
        returncode, output = run_command(command, root)
        if output:
            parts.append(output)
        elif returncode != 0:
            print(f"[WARN] {label} failed", file=sys.stderr)
        parts.append("")

    for rel_path in recommended:
        content = read_file(root, rel_path)
        if content is None:
            continue
        parts.append(f"=== {rel_path} ===")
        parts.append(content.rstrip("\n"))
        parts.append("")

    return "\n".join(parts)


def _skills_root(root: Path) -> Path:
    """Return the canonical ``.agents/skills/yoke`` directory for ``root``.

    This is a pure path join — the resolver never walks ``.claude/skills/yoke``
    (compatibility symlink) nor any home-directory path.
    """
    return root / SKILLS_ROOT_REL


def list_skills(root: Path) -> List[str]:
    """Enumerate top-level Yoke skill names from ``.agents/skills/yoke/``.

    The result always begins with the root router skill ``yoke`` (whose
    ``SKILL.md`` lives directly at the skills root). Named subdirectories are
    included when they contain a ``SKILL.md`` at their top level — this matches
    the convention described in ``AGENTS.md`` ("File Layout") and is how
    operator commands are defined. Phase sub-files (e.g. ``advance/preflight.md``)
    are not standalone skills and are deliberately excluded.

    Raises ``FileNotFoundError`` when the skill tree is missing entirely (no
    ``SKILL.md`` at the skills root). Callers that want a soft-miss can catch
    the exception.
    """
    base = _skills_root(root)
    if not (base / "SKILL.md").is_file():
        raise FileNotFoundError(
            f"Yoke skill root not found at {base} (expected SKILL.md)"
        )
    names: List[str] = [ROOT_SKILL_NAME]
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if (child / "SKILL.md").is_file():
            names.append(child.name)
    return names


def resolve_skill_path(root: Path, name: str) -> Path:
    """Resolve a Yoke skill name to its canonical ``SKILL.md`` path.

    - ``name == "yoke"`` → ``.agents/skills/yoke/SKILL.md``
    - any other name → ``.agents/skills/yoke/<name>/SKILL.md``

    Always returns the absolute ``.agents/...`` form. The resolver does not
    follow the ``.claude/skills/yoke`` compatibility symlink and does not
    probe home-directory fallbacks (``~/.agents``, ``~/.codex/skills``). When
    the target file does not exist, raises ``FileNotFoundError`` with a clear
    message — callers that shell out should surface it as a non-zero exit.
    """
    base = _skills_root(root)
    if name == ROOT_SKILL_NAME:
        path = base / "SKILL.md"
    else:
        path = base / name / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"Yoke skill '{name}' not found at {path}"
        )
    return path.absolute()


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point."""
    args = argv if argv is not None else sys.argv[1:]

    if len(args) < 1:
        print(
            "usage: python3 -m runtime.harness.bootstrap "
            "<required-files|doctrine-short|render-compact|render-full"
            "|skill-list|skill-path> "
            "[--spec SPEC] [--root ROOT] [--extra-file PATH ...] [SKILL_NAME]",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = args[0]
    spec_path: Optional[Path] = None
    root: Optional[Path] = None
    extra_files: List[str] = []
    positional: List[str] = []

    i = 1
    while i < len(args):
        if args[i] == "--spec" and i + 1 < len(args):
            spec_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--root" and i + 1 < len(args):
            root = Path(args[i + 1])
            i += 2
        elif args[i] == "--extra-file" and i + 1 < len(args):
            extra_files.append(args[i + 1])
            i += 2
        elif args[i].startswith("--"):
            print(f"unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(1)
        else:
            positional.append(args[i])
            i += 1

    if root is None:
        root = Path.cwd()

    # Skill-discovery modes do not consume the bootstrap spec and must not
    # require ``--spec``; they operate purely against ``.agents/skills/yoke``.
    if mode == "skill-list":
        try:
            for name in list_skills(root):
                print(name)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
        return

    if mode == "skill-path":
        if len(positional) != 1:
            print(
                "skill-path requires exactly one skill name argument",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            print(resolve_skill_path(root, positional[0]))
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
        return

    if positional:
        print(f"unknown argument: {positional[0]}", file=sys.stderr)
        sys.exit(1)

    if spec_path is None:
        print("--spec is required", file=sys.stderr)
        sys.exit(1)

    spec = load_spec(spec_path)

    if mode == "required-files":
        print(render_required_files(spec, extra_files))
    elif mode == "doctrine-short":
        short = doctrine_short(root)
        if short:
            print(short)
    elif mode == "render-compact":
        print(render_compact(root, spec, extra_files))
    elif mode == "render-full":
        print(render_full(root, spec, extra_files))
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
