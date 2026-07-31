"""Applicability vocabulary for health checks.

A health check is not universally meaningful. Some checks read a project's
source tree, some only make sense against the project that owns this Yoke
installation, some need a capability the project may not declare, and some
cannot run at all on a runner with no filesystem. Before this vocabulary
existed every check shipped to every install and the runner reconciled the
mismatch invisibly: a source-tree scan on a runner with no checkout found
nothing and reported ``PASS``, and one hard-coded slug list was dropped
outright with no trace in the report.

Each check now declares what it applies to, the runner derives the
applicable set from the live context, and anything outside that set is
reported as :data:`NOT_APPLICABLE` with the reason — never silently passed
and never silently dropped.

Four axes:

``project_scope``
    Whether the check targets this installation's own project
    (:data:`PROJECT_SCOPE_SELF`), only other projects
    (:data:`PROJECT_SCOPE_EXTERNAL`), or any project
    (:data:`PROJECT_SCOPE_ANY`).

``requires_source_checkout``
    Whether the check reads the target project's source tree. Only a runner
    that can see that checkout can answer it.

``runtimes``
    Which deployment destinations the check runs under —
    :data:`RUNTIME_LOCAL` (this machine's own universe),
    :data:`RUNTIME_SERVER` (a self-hosted team server), or
    :data:`RUNTIME_HOSTED` (the hosted platform).

``required_capabilities``
    Capability types the target project must declare for the check to have a
    subject at all (``migration_model``, ``health-endpoint``, ``ssh``, ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from yoke_contracts.deployment_destination import (
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
)


RUNTIME_LOCAL = DESTINATION_LOCAL
RUNTIME_SERVER = DESTINATION_SERVER
RUNTIME_HOSTED = DESTINATION_HOSTED

#: Every deployment destination a check may declare.
RUNTIMES = frozenset({RUNTIME_LOCAL, RUNTIME_SERVER, RUNTIME_HOSTED})

#: Runtimes that execute checks where a project checkout can exist. A server
#: runs the engine in a container built from the wheel; only the local
#: universe runs it on the machine that holds the source.
CHECKOUT_BEARING_RUNTIMES = frozenset({RUNTIME_LOCAL})

PROJECT_SCOPE_ANY = "any"
PROJECT_SCOPE_SELF = "self"
PROJECT_SCOPE_EXTERNAL = "external"
PROJECT_SCOPES = frozenset({
    PROJECT_SCOPE_ANY, PROJECT_SCOPE_SELF, PROJECT_SCOPE_EXTERNAL,
})

#: Result severity for a check the live context puts out of scope. Distinct
#: from PASS (the check ran and found nothing) and from omission (the check
#: never appeared in the report at all).
NOT_APPLICABLE = "N/A"


@dataclass(frozen=True)
class CheckApplicability:
    """What one health check applies to."""

    project_scope: str = PROJECT_SCOPE_ANY
    requires_source_checkout: bool = False
    runtimes: frozenset = RUNTIMES
    required_capabilities: tuple = ()

    def __post_init__(self) -> None:
        if self.project_scope not in PROJECT_SCOPES:
            raise ValueError(
                f"project_scope must be one of {sorted(PROJECT_SCOPES)}; "
                f"got {self.project_scope!r}"
            )
        unknown = set(self.runtimes) - RUNTIMES
        if unknown:
            raise ValueError(
                f"unknown runtime(s) {sorted(unknown)}; "
                f"valid runtimes are {sorted(RUNTIMES)}"
            )
        if not self.runtimes:
            raise ValueError("a check must declare at least one runtime")


#: Declaration for a check that reads only the control-plane database: it
#: applies to every project, on every runtime, with no capability or
#: checkout precondition.
UNIVERSAL = CheckApplicability()


@dataclass(frozen=True)
class DoctorContext:
    """The live facts one doctor run derives its applicable set from."""

    project: str
    runtime: str
    self_project: Optional[str] = None
    source_checkout: Optional[Path] = None
    capabilities: frozenset = field(default_factory=frozenset)

    @property
    def targets_self_project(self) -> bool:
        """Whether this run targets the project that owns this install."""
        if self.self_project is None:
            return False
        return str(self.project) == str(self.self_project)


def not_applicable_reason(
    applicability: CheckApplicability, context: DoctorContext,
) -> Optional[str]:
    """Why *applicability* is out of scope for *context*, or ``None``.

    ``None`` means the check applies and must run. Any other value is the
    operator-facing reason recorded alongside the :data:`NOT_APPLICABLE`
    result, so a reader can tell an inapplicable check from a passing one.
    """
    if applicability.runtimes and context.runtime not in applicability.runtimes:
        return (
            f"declared for the {_join(sorted(applicability.runtimes))} "
            f"runtime; this run is {context.runtime}"
        )

    if applicability.project_scope == PROJECT_SCOPE_SELF:
        if context.self_project is None:
            return (
                "targets the project that owns this Yoke installation; "
                "this runner has no self project"
            )
        if not context.targets_self_project:
            return (
                "targets the project that owns this Yoke installation "
                f"({context.self_project}); this run targets "
                f"{context.project}"
            )
    elif applicability.project_scope == PROJECT_SCOPE_EXTERNAL:
        if context.targets_self_project:
            return (
                "targets projects other than the one that owns this Yoke "
                f"installation; this run targets {context.project}"
            )

    if applicability.requires_source_checkout and context.source_checkout is None:
        return (
            f"reads the {context.project} source tree; this runner has no "
            f"checkout for it ({context.runtime} runtime)"
        )

    missing = [
        capability for capability in applicability.required_capabilities
        if capability not in context.capabilities
    ]
    if missing:
        return (
            f"needs the {_join(missing)} capability; "
            f"{context.project} does not declare it"
        )

    return None


def _join(values) -> str:
    values = list(values)
    if len(values) == 1:
        return str(values[0])
    return ", ".join(str(v) for v in values[:-1]) + f" or {values[-1]}"


__all__ = [
    "CHECKOUT_BEARING_RUNTIMES",
    "CheckApplicability",
    "DoctorContext",
    "NOT_APPLICABLE",
    "PROJECT_SCOPES",
    "PROJECT_SCOPE_ANY",
    "PROJECT_SCOPE_EXTERNAL",
    "PROJECT_SCOPE_SELF",
    "RUNTIMES",
    "RUNTIME_HOSTED",
    "RUNTIME_LOCAL",
    "RUNTIME_SERVER",
    "UNIVERSAL",
    "not_applicable_reason",
]
