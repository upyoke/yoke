"""Register the project-install handlers (``project.install/refresh/uninstall``)."""

from __future__ import annotations

from yoke_core.domain.handlers import project_install_handlers as h


def register(registry) -> None:
    rows = (
        ("project.install.run", h.handle_project_install,
         h.ProjectInstallRequest, h.ProjectInstallResponse,
         ["project_repo_file_write", "machine_config_file_write"]),
        ("project.refresh.run", h.handle_project_refresh,
         h.ProjectInstallRequest, h.ProjectInstallResponse,
         ["project_repo_file_write", "machine_config_file_write"]),
        ("project.uninstall.run", h.handle_project_uninstall,
         h.ProjectUninstallRequest, h.ProjectUninstallResponse,
         ["project_repo_file_write"]),
    )
    for function_id, handler, request_model, response_model, side_effects in rows:
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="beta",
            owner_module=__name__,
            target_kinds=["system"],
            side_effects=side_effects,
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
        )


__all__ = ["register"]
