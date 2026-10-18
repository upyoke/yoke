"""Converge machine and registered-folder setup through existing harness owners."""

from __future__ import annotations

import io
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

from yoke_cli.config.machine_config import configured_projects
from yoke_contracts import harness_unattended_posture as posture
from yoke_contracts.codex_hook_trust_store import (
    inspect_hook_file_trust,
    mint_installed_checkout_trust,
    retrust_recovery,
)
from yoke_contracts.codex_lane_hook_trust import inspect_hook_trust, mirror_hook_trust
from yoke_contracts.harness_folder_trust import claude_state_path, cursor_trust_file
from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
from yoke_contracts.harness_posture_install import configure_harness_unattended_posture
from yoke_contracts.machine_config.checkout import (
    main_checkout,
    registered_worktree_paths,
)
from yoke_harness.hooks.machine_hooks import ensure_machine_hooks
from yoke_harness.hooks.machine_hooks_inspect import inspect_machine_hooks

RECOVERY = (
    "Run `yoke doctor run --only harness-setup --fix` after repairing the named file."
)
FAILURES = {"refused", "failed"}


@dataclass(frozen=True)
class HarnessSetupRow:
    target_path: str
    harness_id: str
    facet: str
    outcome: str
    detail: str = ""
    recovery: str = ""

    def line(self) -> str:
        return (
            f"{self.harness_id}: {self.facet} {self.outcome} {self.target_path} "
            f"{self.detail} {self.recovery}"
        ).strip()


@dataclass(frozen=True)
class HarnessSetupResult:
    rows: tuple[HarnessSetupRow, ...]

    @property
    def failed(self) -> bool:
        return any(row.outcome in FAILURES for row in self.rows)

    def payload(self) -> dict:
        return {"rows": [asdict(row) for row in self.rows], "failed": self.failed}

    def lines(self) -> list[str]:
        return [row.line() for row in self.rows]


def _document(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    doc = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)
    if not isinstance(doc, dict):
        raise ValueError(f"harness_config_malformed: {path}: expected an object")
    return doc


def _folder(path: Path, harness: str) -> tuple[bool, str]:
    if harness == "claude-code":
        target = claude_state_path()
        doc = _document(target)
        projects = doc.get("projects", {})
        if not isinstance(projects, dict) or not isinstance(
            projects.get(str(path), {}), dict
        ):
            raise ValueError(
                f"harness_config_malformed: {target}: projects entry is not an object"
            )
        ready = projects.get(str(path), {}).get("hasTrustDialogAccepted") is True
    elif harness == "codex":
        target = posture.codex_config_path()
        doc = _document(target)
        ready = (
            doc.get("projects", {}).get(str(path), {}).get("trust_level") == "trusted"
        )
    else:
        target = cursor_trust_file(path)
        ready = _document(target).get("workspacePath") == str(path)
    return ready, f"folder_trust_missing: {target}: {path}"


def _posture(harness: str) -> tuple[bool, str]:
    target = posture.managed_config_paths()[harness]
    doc = _document(target)
    for key in ("preferences", posture.CURSOR_SANDBOX_CONTAINER):
        if key in doc and not isinstance(doc[key], dict):
            raise ValueError(
                f"harness_config_malformed: {target}: {key} is not an object"
            )
    problems = list(posture.posture_problems(harness, doc))
    if harness == "claude-code":
        settings = posture.claude_settings_path()
        settings_doc = _document(settings)
        if "permissions" in settings_doc and not isinstance(
            settings_doc["permissions"], dict
        ):
            raise ValueError(
                f"harness_config_malformed: {settings}: permissions is not an object"
            )
        problems.extend(posture.claude_settings_problems(settings_doc))
        # Desktop preferences apply only when the desktop has created its config.
        if not target.exists():
            problems = list(posture.claude_settings_problems(_document(settings)))
        target = settings
    return not problems, f"harness_posture_missing: {target}: {'; '.join(problems)}"


def _hooks(path: Path, source: Path, *, apply: bool) -> tuple[bool, str]:
    if path == source:
        if apply:
            mint_installed_checkout_trust(path)
        result = inspect_hook_file_trust(path / ".codex/hooks.json")
        return result.approved, result.summary()
    result = (mirror_hook_trust if apply else inspect_hook_trust)(
        str(source), str(path)
    )
    return result.hooks_fire, result.summary()


def _machine_hooks(harness: str) -> tuple[bool, str]:
    result = next(row for row in inspect_machine_hooks() if row.harness_id == harness)
    reason = (
        "machine_hooks_config_malformed"
        if result.outcome == "malformed"
        else f"machine_hooks_{result.outcome}"
    )
    return result.outcome == "installed", f"{reason}: {result.line()}"


def _facet(
    target: Path,
    harness: str,
    name: str,
    inspect: Callable,
    write: Callable,
    apply: bool,
    recovery: str = RECOVERY,
) -> HarnessSetupRow:
    try:
        ready, detail = inspect()
        if ready:
            return HarnessSetupRow(str(target), harness, name, "already_set")
        output = ""
        if apply:
            output = str(write() or "")
            ready, detail = inspect()
        outcome = "written" if ready else "refused"
        return HarnessSetupRow(
            str(target),
            harness,
            name,
            outcome,
            "" if ready else f"harness_setup_incomplete: {detail}; {output}",
            "" if ready else recovery,
        )
    except Exception as exc:  # each facet must leave the rest runnable
        return HarnessSetupRow(
            str(target),
            harness,
            name,
            "failed",
            f"harness_state_unwritable_or_malformed: {exc}",
            RECOVERY,
        )


def _targets(
    paths: Sequence[Path] | None, rows: list[HarnessSetupRow]
) -> list[tuple[Path, Path]]:
    roots = (
        [Path(path).expanduser().resolve() for path in paths]
        if paths is not None
        else [
            entry.checkout.resolve()
            for entry in configured_projects(existing_only=True)
        ]
    )
    targets: dict[Path, Path] = {}
    for root in roots:
        try:
            source = main_checkout(root)
            for path in (
                [root] if paths is not None else registered_worktree_paths(root)
            ):
                targets[path] = source
        except Exception as exc:
            rows.append(
                HarnessSetupRow(
                    str(root),
                    "all",
                    "target_inventory",
                    "failed",
                    f"harness_targets_unavailable: {exc}",
                    RECOVERY,
                )
            )
    return sorted(targets.items(), key=lambda pair: (pair[0] != pair[1], str(pair[0])))


def _walk(
    paths: Sequence[Path] | None, *, apply: bool, include_posture: bool = True
) -> HarnessSetupResult:
    rows: list[HarnessSetupRow] = []
    try:
        targets = _targets(paths, rows)
    except Exception as exc:
        targets = []
        rows.append(
            HarnessSetupRow(
                "machine",
                "all",
                "target_inventory",
                "failed",
                f"harness_targets_unavailable: {exc}",
                RECOVERY,
            )
        )
    for harness, spec in HARNESS_MACHINE_HOOKS.items():
        home = spec.home_path()
        if not home.is_dir():
            for target, _source in targets or [(home, home)]:
                for facet in ("folder_trust", "hook_trust", "posture", "machine_hooks"):
                    rows.append(
                        HarnessSetupRow(
                            str(target), harness, facet, "skipped_not_installed"
                        )
                    )
            continue
        for target, source in targets:
            rows.append(
                _facet(
                    target,
                    harness,
                    "folder_trust",
                    lambda: _folder(target, harness),
                    lambda: grant_folder_trust(target, harnesses=(harness,)),
                    apply,
                )
            )
            if harness == "codex":
                rows.append(
                    _facet(
                        target,
                        harness,
                        "hook_trust",
                        lambda: _hooks(target, source, apply=False),
                        lambda: _hooks(target, source, apply=True),
                        apply,
                        retrust_recovery(target),
                    )
                )
        if include_posture:
            rows.append(
                _facet(
                    home,
                    harness,
                    "posture",
                    lambda: _posture(harness),
                    lambda: configure_harness_unattended_posture(
                        harnesses=(harness,), stream=io.StringIO()
                    ),
                    apply,
                )
            )
        rows.append(
            _facet(
                home,
                harness,
                "machine_hooks",
                lambda: _machine_hooks(harness),
                lambda: ensure_machine_hooks([harness]),
                apply,
            )
        )
    return HarnessSetupResult(tuple(rows))


def inspect_harness_setup(paths: Sequence[Path] | None = None) -> HarnessSetupResult:
    """Inspect the same targets and facets without writing any harness state."""
    return _walk(paths, apply=False)


def reconcile_harness_setup(
    paths: Sequence[Path] | None = None, *, include_posture: bool = True
) -> HarnessSetupResult:
    """Apply every facet; an explicit setup permission decline omits posture."""
    return _walk(paths, apply=True, include_posture=include_posture)
