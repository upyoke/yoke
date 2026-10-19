"""Install the user-level ``yoke-global`` skill for every installed harness.

Facts come from :mod:`yoke_contracts.harness_global_skill`: one shared folder
``~/.agents/skills/yoke-global`` that Codex and Cursor read, plus a symlink
for each ``link`` harness (Claude Code). A harness whose home folder is
absent is not installed; the installer names it and never creates its home.

Every folder or link Yoke creates is recorded in the harness settings ledger
(:mod:`yoke_contracts.harness_settings_ledger`) as a ``created_dir`` entry, so
``yoke uninstall`` removes it. Parent folders the install had to create
(``~/.agents``, ``~/.agents/skills``, ``~/.claude/skills``) are recorded as
``created_parent_dir`` and removed only while empty. A folder or link already present that Yoke did
not record is never overwritten: install refuses with
``global_skill_path_not_owned``, the path and the recovery step.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.harness_global_skill import (
    HARNESS_GLOBAL_SKILLS,
    link_path,
    shared_skill_dir,
)
from yoke_contracts.harness_machine_hooks import machine_hooks_for_harness

SKILL_FILE = "SKILL.md"
NOT_OWNED = "global_skill_path_not_owned"
NO_HARNESS = "no_harness_installed"


@dataclass
class GlobalSkillResult:
    """What one install pass did; ``reason`` is set when it refused."""

    lines: List[str] = field(default_factory=list)
    reason: str = ""
    recovery: str = ""

    @property
    def refused(self) -> bool:
        return bool(self.reason) and self.reason != NO_HARNESS

    @property
    def warning(self) -> str:
        """The refusal as one line; empty unless the install refused."""
        if not self.refused:
            return ""
        return f"yoke-global skill not installed: {self.reason}: {self.recovery}"

    def to_json(self) -> dict:
        return {"lines": self.lines, "reason": self.reason, "recovery": self.recovery}


def skill_text() -> str:
    """The shipped skill body, the one source every placement serves."""
    return (
        resources.files("yoke_contracts")
        .joinpath("global_skill", SKILL_FILE)
        .read_text(encoding="utf-8")
    )


def user_home(environ: Optional[Mapping[str, str]] = None) -> Path:
    """The home folder the shared skill folder and link harnesses live in."""
    env = os.environ if environ is None else environ
    return Path(env.get("HOME") or str(Path.home()))


def ensure_global_skill(
    environ: Optional[Mapping[str, str]] = None,
) -> GlobalSkillResult:
    """Install or refresh the skill; never raises for an expected refusal.

    A harness counts as installed when its home exists, resolved by
    :meth:`HarnessMachineHooks.home_path` (``CODEX_HOME`` included), the same
    rule the machine-wide hooks use.
    """
    home = user_home(environ)
    result = GlobalSkillResult()
    installed = [
        h
        for h in HARNESS_GLOBAL_SKILLS
        if machine_hooks_for_harness(h).home_path(environ).is_dir()
    ]
    if not installed:
        result.reason = NO_HARNESS
        result.lines.append(
            "yoke-global skill: no Claude Code, Codex or Cursor home folder "
            "found; nothing installed. Run `yoke setup` again after installing one."
        )
        return result
    owned = _owned_paths()
    shared = shared_skill_dir(home)
    if not _install_shared(shared, owned, result):
        return result
    for harness_id in HARNESS_GLOBAL_SKILLS:
        if harness_id not in installed:
            result.lines.append(f"{harness_id}: not installed; skipped")
            continue
        if HARNESS_GLOBAL_SKILLS[harness_id].placement == "shared":
            result.lines.append(f"{harness_id}: reads {shared}")
            continue
        link = link_path(harness_id, home)
        if not _install_link(link, shared, owned, result):
            return result
        result.lines.append(f"{harness_id}: {link} -> {shared}")
    return result


def global_skill_ready(
    harness_id: str, environ: Optional[Mapping[str, str]] = None
) -> tuple[bool, str]:
    """Whether *harness_id* discovers the current skill; detail names the gap."""
    home = user_home(environ)
    shared = shared_skill_dir(home)
    target = shared / SKILL_FILE
    if not target.is_file() or target.read_text(encoding="utf-8") != skill_text():
        return False, f"global_skill_missing: {target}"
    if HARNESS_GLOBAL_SKILLS[harness_id].placement == "link":
        link = link_path(harness_id, home)
        if not link.is_symlink() or link.resolve() != shared.resolve():
            return False, f"global_skill_link_missing: {link}"
    return True, ""


def _install_shared(shared: Path, owned: set, result: GlobalSkillResult) -> bool:
    text = skill_text()
    target = shared / SKILL_FILE
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return _record(shared, result)
    if (shared.exists() or shared.is_symlink()) and str(shared) not in owned:
        return _refuse(shared, result)
    parents = _missing_parents(shared)
    shared.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return _record(shared, result, parents)


def _install_link(
    link: Path, shared: Path, owned: set, result: GlobalSkillResult
) -> bool:
    if link.is_symlink() and link.resolve() == shared.resolve():
        return _record(link, result)
    if link.exists() or link.is_symlink():
        if str(link) not in owned:
            return _refuse(link, result)
        link.unlink()
    parents = _missing_parents(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(shared, target_is_directory=True)
    return _record(link, result, parents)


def _missing_parents(path: Path) -> List[Path]:
    """Folders above *path* that do not exist yet, deepest first."""
    missing: List[Path] = []
    for parent in path.parents:
        if parent.exists() or parent.is_symlink():
            break
        missing.append(parent)
    return missing


def _record(
    path: Path, result: GlobalSkillResult, parents: Sequence[Path] = ()
) -> bool:
    """Record *path*, then the parents created for it, deepest first."""
    entries = [ledger.created_dir_entry(path)]
    entries += [ledger.created_parent_dir_entry(parent) for parent in parents]
    for entry in entries:
        problem = ledger.record(entry)
        if problem:
            result.lines.append(problem)
    return True


def _refuse(path: Path, result: GlobalSkillResult) -> bool:
    result.reason = NOT_OWNED
    result.recovery = (
        f"{path} already exists and Yoke did not create it. Move it aside, "
        "then run `yoke doctor run --only harness-setup --fix`; it works "
        "outside a project."
    )
    result.lines.append(result.warning)
    return False


def _owned_paths() -> set:
    try:
        entries = ledger.read()
    except (OSError, ValueError):
        return set()
    return {e.get("file") for e in entries if e.get("kind") == "created_dir"}


__all__ = [
    "GlobalSkillResult",
    "NOT_OWNED",
    "NO_HARNESS",
    "ensure_global_skill",
    "global_skill_ready",
    "skill_text",
]
