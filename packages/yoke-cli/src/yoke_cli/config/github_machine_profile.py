"""Profile selection and replacement guard for machine GitHub connect."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_machine_state as state
from yoke_cli.config import machine_config


def resolve(
    *,
    config_path: str | Path | None,
    client_id: str | None,
    app_slug: str | None,
    app_id: int | str | None,
    api_url: str | None,
    web_url: str | None,
    service_api_url: str | None,
    use_local_product_profile: bool,
    profile_opener: Callable[..., Any] | None,
    replace_profile: bool,
    error_type: type[RuntimeError],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve one authoritative profile and guard saved-profile replacement."""

    try:
        existing = state.existing_config(config_path)
        explicit = (client_id, app_slug, app_id, api_url, web_url)
        if use_local_product_profile and (
            str(service_api_url or "").strip()
            or any(value not in (None, "") for value in explicit)
        ):
            raise github_app_public_profile.GitHubAppPublicProfileError(
                "the bundled local product App cannot be combined with a "
                "service or explicit App profile"
            )
        if str(service_api_url or "").strip():
            metadata = github_app_public_profile.service_metadata(
                github_app_public_profile.fetch(
                    str(service_api_url), opener=profile_opener,
                ),
                service_api_url=str(service_api_url),
            )
        elif use_local_product_profile:
            metadata = github_app_public_profile.local_product_metadata()
        elif any(value not in (None, "") for value in explicit):
            configured = machine_config.load_config(config_path)
            if configured.get("connections") and (
                github_app_public_profile.selected_https_service_api_url(
                    config_path
                ) is not None
            ):
                raise github_app_public_profile.GitHubAppPublicProfileError(
                    "explicit GitHub App profile fields are only valid for a "
                    "local Yoke connection; HTTPS connections must use their "
                    "selected service health profile"
                )
            metadata = state.public_app_metadata(
                service_api_url=None,
                client_id=client_id,
                app_slug=app_slug,
                app_id=app_id,
                api_url=api_url,
                web_url=web_url,
                opener=profile_opener,
            )
        else:
            selected = github_app_public_profile.selected_https_service_api_url(
                config_path
            )
            metadata = (
                github_app_public_profile.local_product_metadata()
                if selected is None
                else github_app_public_profile.service_metadata(
                    github_app_public_profile.fetch(
                        selected, opener=profile_opener,
                    ),
                    service_api_url=selected,
                )
            )
        identity_fields = (
            "client_id", "app_slug", "app_id", "api_url", "web_url",
            "profile_source", "profile_service_api_url",
        )
        if existing and any(
            existing.get(field) != metadata.get(field)
            for field in identity_fields
        ) and not replace_profile:
            raise github_app_public_profile.GitHubAppPublicProfileError(
                "the saved machine GitHub authorization belongs to a different "
                "Yoke GitHub App profile; use the explicit reconnect action or "
                "run `yoke github connect --replace` against the selected service"
            )
        return existing, metadata
    except (
        ValueError,
        machine_config.MachineConfigError,
        github_app_public_profile.GitHubAppPublicProfileError,
    ) as exc:
        raise error_type(str(exc)) from exc


__all__ = ["resolve"]
