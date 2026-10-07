"""The GitHub access a CI-gated release's source reads need, and their refusals.

Creating a CI-gated release reads the CI workflow's runs (Actions) and the
gate branch's commits and comparisons (Contents). A public repository answers
the Contents reads with any token; a private one answers only a token scoped
to ``contents: read``, so the token is minted with every permission declared
here. A read GitHub refuses for authorization names that set and its repair,
because retrying the same token cannot succeed.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
)

CI_GATE_READ_PERMISSIONS: Mapping[str, str] = MappingProxyType(
    {
        **GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
        **GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
    }
)


def read_refusal(target: Any, path: str, exc: Exception, purpose: str) -> Exception:
    """Name why GitHub would not answer *path* and what repairs it.

    *purpose* completes "could not read PATH ..." for a transient failure.
    """
    from yoke_core.domain.deployment_run_ci_tested_source import (
        UNVERIFIABLE,
        ReleaseSourceRefused,
    )
    from yoke_core.domain.gh_rest_transport import RestAuthError
    from yoke_core.domain.project_github_auth import repair_command_hint
    from yoke_core.domain.project_github_auth_models import MissingPermission

    if isinstance(exc, RestAuthError):
        needed = ", ".join(
            f"{name}: {access}" for name, access in CI_GATE_READ_PERMISSIONS.items()
        )
        repair = repair_command_hint(
            MissingPermission(target.project, ""), target.project
        )
        return ReleaseSourceRefused(
            UNVERIFIABLE,
            f"GitHub refused {path} in {target.repo}: {exc}. The CI gate's "
            f"reads need project '{target.project}' GitHub App access to "
            f"{target.repo} with {needed}; a retry with the same access "
            f"fails the same way. Nothing was created.\n  Repair: {repair}, "
            "then create the run again.",
        )
    return ReleaseSourceRefused(
        UNVERIFIABLE,
        f"could not read {path} {purpose}: {exc}. Retry the create; nothing "
        "was created.",
    )


__all__ = ["CI_GATE_READ_PERMISSIONS", "read_refusal"]
