"""Readable account of which lint-config decided each guard's mode.

``.yoke/lint-config`` is tracked, so a repository and each of its linked
worktrees carry independent copies, and the copy that governs a hook is
the one under the resolved workspace root. Two failure modes follow, and
both are silent without a report like this one:

* an edit lands in a copy the hook never reads, so nothing changes;
* a ``warn`` line on a protected guard is clamped back to ``deny``
  because it omits the ``# allow-warn`` token, so the file reads as
  edited while enforcement is unchanged.

This module answers both by naming the resolved root, how that root was
chosen, and — per guard — what the file declared next to what is
actually in force.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from yoke_contracts.hook_runner import lint_policy

# ``root_source`` values.
SOURCE_EXPLICIT = "explicit"
SOURCE_DIRECTORY_SEARCH = "directory_search"
SOURCE_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class GuardReport:
    """One guard's declared-vs-effective enforcement state."""

    guard: str
    effective_mode: str
    declared_mode: Optional[str]
    protected: bool
    allow_warn: bool
    description: str

    @property
    def clamped(self) -> bool:
        """True when a declared ``warn`` was forced back to ``deny``.

        Only protected guards clamp, and only when the ``# allow-warn``
        token is absent. This is the case that most looks like an edit
        that took effect but did not.
        """
        return (
            self.declared_mode == lint_policy.WARN
            and self.effective_mode == lint_policy.DENY
        )

    @property
    def declared(self) -> bool:
        return self.declared_mode is not None

    def as_dict(self) -> Dict[str, object]:
        return {
            "guard": self.guard,
            "effective_mode": self.effective_mode,
            "declared_mode": self.declared_mode,
            "protected": self.protected,
            "allow_warn": self.allow_warn,
            "clamped": self.clamped,
            "description": self.description,
        }


@dataclass(frozen=True)
class ConfigReport:
    """The resolved config file plus every guard's state under it."""

    root: Optional[str]
    root_source: str
    root_env_var: Optional[str]
    config_path: Optional[str]
    config_exists: bool
    guards: List[GuardReport]

    def as_dict(self) -> Dict[str, object]:
        return {
            "root": self.root,
            "root_source": self.root_source,
            "root_env_var": self.root_env_var,
            "config_path": self.config_path,
            "config_exists": self.config_exists,
            "guards": [g.as_dict() for g in self.guards],
        }


def _resolve_root(explicit: Optional[str]) -> tuple[Optional[str], str, Optional[str]]:
    """Return ``(root, root_source, root_env_var)``.

    Mirrors ``lint_policy.find_workspace_root`` selection and additionally
    reports *why* the root was chosen, which the path alone cannot show.
    """
    if explicit:
        return (os.path.abspath(os.path.expanduser(explicit)), SOURCE_EXPLICIT, None)
    for key in lint_policy.WORKSPACE_ROOT_ENV_VARS:
        value = os.environ.get(key)
        if value:
            return (os.path.abspath(os.path.expanduser(value)), SOURCE_EXPLICIT, key)
    found = lint_policy.find_workspace_root()
    if found is None:
        return (None, SOURCE_UNRESOLVED, None)
    return (str(found), SOURCE_DIRECTORY_SEARCH, None)


def build_report(root: Optional[str] = None) -> ConfigReport:
    """Resolve the governing config and report every guard's state."""
    resolved_root, root_source, root_env_var = _resolve_root(root)
    config_path = (
        os.path.join(resolved_root, *lint_policy.CONFIG_RELPATH)
        if resolved_root else None
    )
    entries = lint_policy.parse_file(config_path)

    guards: List[GuardReport] = []
    for spec in lint_policy.GUARD_CATALOG:
        entry = entries.get(spec.guard)
        if entry is None:
            for alias in spec.aliases:
                entry = entries.get(alias)
                if entry is not None:
                    break
        declared_mode, allow_warn = entry if entry is not None else (None, False)
        guards.append(GuardReport(
            guard=spec.guard,
            effective_mode=lint_policy.resolve_mode_from_entries(spec.guard, entries),
            declared_mode=declared_mode,
            protected=spec.protected,
            allow_warn=allow_warn,
            description=spec.description,
        ))

    return ConfigReport(
        root=resolved_root,
        root_source=root_source,
        root_env_var=root_env_var,
        config_path=config_path,
        config_exists=bool(config_path) and os.path.isfile(config_path),
        guards=guards,
    )


def _root_line(report: ConfigReport) -> str:
    if report.root_source == SOURCE_UNRESOLVED:
        return "Root:   <unresolved> — no .yoke/lint-config found above the start directory"
    if report.root_env_var:
        return f"Root:   {report.root} (from ${report.root_env_var})"
    if report.root_source == SOURCE_EXPLICIT:
        return f"Root:   {report.root} (explicitly requested)"
    return f"Root:   {report.root} (found by searching upward from the current directory)"


def render_text(report: ConfigReport) -> str:
    """Render the report for a terminal reader."""
    missing = "" if report.config_exists else "  [MISSING — built-in defaults apply]"
    lines = [
        _root_line(report),
        f"Config: {report.config_path or '<none>'}{missing}",
        "",
    ]
    width = max((len(g.guard) for g in report.guards), default=0)
    for guard in report.guards:
        notes: List[str] = []
        if guard.clamped:
            notes.append(
                f"declared warn, clamped to deny — protected guard needs "
                f"`{lint_policy.ALLOW_WARN_TOKEN}`")
        elif not guard.declared:
            notes.append("not declared — built-in default")
        if guard.protected and not guard.clamped:
            notes.append("protected")
        suffix = f"  ({'; '.join(notes)})" if notes else ""
        lines.append(f"  {guard.guard.ljust(width)}  {guard.effective_mode}{suffix}")

    clamped = [g.guard for g in report.guards if g.clamped]
    if clamped:
        lines += [
            "",
            f"{len(clamped)} declared warn line(s) are NOT in force: "
            + ", ".join(clamped),
        ]
    return "\n".join(lines)
