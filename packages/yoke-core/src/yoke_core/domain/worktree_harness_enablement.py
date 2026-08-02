"""Manifest-driven hook enablement for linked worktree lanes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from yoke_core.domain.worktree_claude_approval import seed_directory_approval


VERIFY_HOOK_CONFIG = "verify_hook_config"
MIRROR_HOOK_TRUST = "mirror_hook_trust"
SEED_DIRECTORY_APPROVAL = "seed_directory_approval"
VERIFY_ENVIRONMENT_EXPORT = "verify_environment_export"


@dataclass(frozen=True)
class HookEnablementContribution:
    """One harness adapter's lane-enablement declaration."""

    harness_id: str
    config_path: str
    operations: Tuple[str, ...]
    root_env_var: str
    root_expression: str
    affordances: Tuple[str, ...]


@dataclass
class HarnessEnablementReport:
    """Actions and warnings produced while preparing one harness lane."""

    harness_id: str
    actions: List[str]
    warnings: List[str]


def load_hook_enablement_contributions(
    adapter_root: Optional[str] = None,
) -> Tuple[HookEnablementContribution, ...]:
    """Load every harness's worktree contribution from its manifest."""
    root = Path(adapter_root).expanduser() if adapter_root else _default_adapter_root()
    manifest_root = root / "runtime" / "harness"
    if not manifest_root.is_dir():
        return ()

    contributions: List[HookEnablementContribution] = []
    for manifest_path in sorted(manifest_root.glob("*/manifest.json")):
        try:
            with manifest_path.open(encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        enablement = manifest.get("worktree_hook_enablement")
        if not isinstance(enablement, dict):
            continue
        environment = enablement.get("environment")
        operations = enablement.get("operations")
        harness_id = manifest.get("harness_id")
        config_path = enablement.get("config_path")
        if not (
            isinstance(harness_id, str)
            and isinstance(config_path, str)
            and isinstance(operations, list)
            and all(isinstance(operation, str) for operation in operations)
            and isinstance(environment, dict)
            and isinstance(environment.get("root_variable"), str)
            and isinstance(environment.get("root_expression"), str)
        ):
            continue
        supports = manifest.get("supports") or {}
        affordances = supports.get("optional_local_affordances") or []
        if not isinstance(affordances, list):
            affordances = []
        contributions.append(
            HookEnablementContribution(
                harness_id=harness_id,
                config_path=config_path,
                operations=tuple(operations),
                root_env_var=environment["root_variable"],
                root_expression=environment["root_expression"],
                affordances=tuple(
                    value for value in affordances if isinstance(value, str)
                ),
            )
        )
    return tuple(contributions)


def prepare_worktree_harnesses(
    source_checkout: str,
    worktree_path: str,
    *,
    adapter_root: Optional[str] = None,
) -> Tuple[HarnessEnablementReport, ...]:
    """Apply each manifest-declared hook-enablement operation to a lane."""
    source = Path(source_checkout).expanduser()
    worktree = Path(worktree_path).expanduser()
    reports: List[HarnessEnablementReport] = []
    for contribution in load_hook_enablement_contributions(adapter_root):
        source_config = source / contribution.config_path
        target_config = worktree / contribution.config_path
        if not target_config.exists():
            if source_config.exists():
                reports.append(
                    HarnessEnablementReport(
                        contribution.harness_id,
                        [],
                        [f"hook config missing from worktree: {target_config}"],
                    )
                )
            continue

        report = HarnessEnablementReport(contribution.harness_id, [], [])
        for operation in contribution.operations:
            _run_operation(
                operation,
                contribution,
                source,
                worktree,
                target_config,
                report,
            )
        reports.append(report)
    return tuple(reports)


def _run_operation(
    operation: str,
    contribution: HookEnablementContribution,
    source: Path,
    worktree: Path,
    target_config: Path,
    report: HarnessEnablementReport,
) -> None:
    if operation == VERIFY_HOOK_CONFIG:
        try:
            with target_config.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("top-level value is not an object")
            if not isinstance(payload.get("hooks"), dict):
                raise ValueError("hooks object is missing")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            report.warnings.append(f"hook config is invalid: {exc}")
        else:
            report.actions.append("verified hook config")
        return

    if operation == MIRROR_HOOK_TRUST:
        from yoke_core.domain.worktree_codex_hook_trust import mirror_hook_trust

        result = mirror_hook_trust(str(source), str(worktree))
        if result.mirrored:
            report.actions.append(f"mirrored {len(result.mirrored)} hook trust entries")
        elif result.blocked_reason and result.source_trusted:
            report.warnings.append(result.blocked_reason)
        return

    if operation == SEED_DIRECTORY_APPROVAL:
        result = seed_directory_approval(str(source), str(worktree))
        if result.seeded:
            report.actions.append("seeded Claude directory approval")
        elif result.blocked_reason and target_config.exists():
            report.warnings.append(result.blocked_reason)
        elif result.write_error:
            report.warnings.append(result.write_error)
        return

    if operation == VERIFY_ENVIRONMENT_EXPORT:
        try:
            config_text = target_config.read_text(encoding="utf-8")
        except OSError as exc:
            report.warnings.append(f"hook config could not be read: {exc}")
        else:
            if f"{contribution.root_env_var}=" not in config_text:
                report.warnings.append(
                    f"hook commands do not export {contribution.root_env_var}"
                )
            else:
                report.actions.append(
                    f"verified {contribution.root_env_var} lane export"
                )
        return

    report.warnings.append(f"unsupported enablement operation: {operation}")


def _default_adapter_root() -> Path:
    """Find the checkout that owns this installed Yoke source."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "runtime" / "harness").is_dir():
            return parent
    return Path(__file__).resolve().parents[5]


__all__ = [
    "HookEnablementContribution",
    "HarnessEnablementReport",
    "MIRROR_HOOK_TRUST",
    "SEED_DIRECTORY_APPROVAL",
    "VERIFY_ENVIRONMENT_EXPORT",
    "VERIFY_HOOK_CONFIG",
    "load_hook_enablement_contributions",
    "prepare_worktree_harnesses",
]
