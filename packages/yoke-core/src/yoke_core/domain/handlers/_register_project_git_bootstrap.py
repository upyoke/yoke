"""Handler registration for ``project.git.bootstrap``."""

from __future__ import annotations

from yoke_core.domain.handlers import project_git_bootstrap as _pgb


def register(registry) -> None:
    registry.register(
        "project.git.bootstrap",
        _pgb.handle_project_git_bootstrap,
        _pgb.ProjectGitBootstrapRequest,
        _pgb.ProjectGitBootstrapResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_git_bootstrap",
        target_kinds=["global"],
        side_effects=["project_repo_file_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
