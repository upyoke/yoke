"""Runner dispatch for governed migration apply.

One runner kind is wired today: ``governed_migration_module``. It is the
project-configured Python migration-module capability Yoke already uses:
load ``<identifier>.py`` from ``runner.config.modules_dir`` and call its
``apply(conn)`` function. Yoke, Buzz, and future webapp projects all
use the same runner kind; only the configured modules directory and
connection env var vary by project.

The dispatch returns a :class:`RunnerHandle` that quacks like a
``ModuleType`` for the rehearse/live call sites: ``handle.apply(conn)``
runs the migration; ``getattr(handle, "invariants", None)`` returns the
optional callable. ``handle.identifier`` echoes the per-row identity the
audit-row writer uses.

Runner-kind branching lives ONLY in this module: rehearse/live
call :func:`dispatch_handle` and never inspect ``model.runner.kind``
themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, FrozenSet, Mapping, Optional

from yoke_core.domain.migration_apply_contract import (
    ModuleResolutionError,
)
from yoke_core.domain.migration_apply_resolve import (
    ModuleOverrideResolution,
    load_module_with_override as _load_module_with_override,
)
from yoke_core.domain.migration_model_capability_validation import (
    RUNNER_KIND_GOVERNED_MODULE,
)

_KNOWN_RUNNER_KINDS: FrozenSet[str] = frozenset({
    RUNNER_KIND_GOVERNED_MODULE,
})


class UnknownRunnerKind(ValueError):
    """Raised when a model declares a runner kind not known to dispatch.

    The message carries ``project``, ``model``, and ``known_kinds`` so the
    operator-facing error names the exact config to amend.
    """

    def __init__(
        self,
        kind: Any,
        *,
        project: Optional[str] = None,
        model: Optional[str] = None,
        known_kinds: Optional[FrozenSet[str]] = None,
    ) -> None:
        self.kind = kind
        self.project = project
        self.model = model
        self.known_kinds = known_kinds or _KNOWN_RUNNER_KINDS
        parts = [f"runner.kind {kind!r} is not registered"]
        if project:
            parts.append(f"project={project!r}")
        if model:
            parts.append(f"model={model!r}")
        parts.append(f"known kinds: {sorted(self.known_kinds)}")
        super().__init__("; ".join(parts))


@dataclass(frozen=True)
class RunnerHandle:
    """Quack-like object with ``.apply(conn)`` consumed by rehearse/live.

    The handle wraps a Python ``ModuleType`` and forwards ``apply`` /
    ``invariants`` to module attributes.
    """

    kind: str
    identifier: str
    apply: Callable[[Any], None]
    invariants: Optional[Callable[[Any], None]]
    source_path: Path


def known_runner_kinds() -> FrozenSet[str]:
    """Return the immutable set of runner kinds dispatch can route."""
    return _KNOWN_RUNNER_KINDS


def runner_kind_of(model: Mapping[str, Any]) -> str:
    return str((model.get("runner") or {}).get("kind") or "")


def dispatch_handle(
    *,
    model: Mapping[str, Any],
    repo_path: Path,
    identifier: str,
    override: Optional[ModuleOverrideResolution] = None,
    project: Optional[str] = None,
    model_name: Optional[str] = None,
) -> RunnerHandle:
    """Return a :class:`RunnerHandle` for *identifier* under *model*.

    *repo_path* is the active worktree root (rehearse) or the repo root
    (live), joined with the runner-config directory to resolve where to
    find the migration.
    """
    kind = runner_kind_of(model)
    if kind == RUNNER_KIND_GOVERNED_MODULE:
        return _dispatch_governed_module(
            model=model,
            repo_path=repo_path,
            identifier=identifier,
            override=override,
        )
    raise UnknownRunnerKind(
        kind, project=project, model=model_name,
        known_kinds=_KNOWN_RUNNER_KINDS,
    )


def _dispatch_governed_module(
    *,
    model: Mapping[str, Any],
    repo_path: Path,
    identifier: str,
    override: Optional[ModuleOverrideResolution],
) -> RunnerHandle:
    config = (model.get("runner") or {}).get("config") or {}
    modules_dir_rel = config.get("modules_dir")
    if not modules_dir_rel:
        raise ModuleResolutionError(
            f"runner.config.modules_dir missing for governed_migration_module "
            f"(identifier {identifier!r})"
        )
    modules_dir = (repo_path / modules_dir_rel).resolve()
    module = _load_module_with_override(
        modules_dir=modules_dir, identifier=identifier, override=override,
    )
    source_path = (
        Path(override.module_path) if override is not None and override.slug == identifier
        else modules_dir / f"{identifier}.py"
    )
    invariants = getattr(module, "invariants", None)
    if not callable(invariants):
        invariants = None
    return RunnerHandle(
        kind=RUNNER_KIND_GOVERNED_MODULE,
        identifier=identifier,
        apply=module.apply,
        invariants=invariants,
        source_path=source_path,
    )


__all__ = [
    "RUNNER_KIND_GOVERNED_MODULE",
    "RunnerHandle",
    "UnknownRunnerKind",
    "dispatch_handle",
    "known_runner_kinds",
    "runner_kind_of",
]
