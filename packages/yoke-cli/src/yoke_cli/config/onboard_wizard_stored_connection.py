"""Preload of stored machine-config references into the wizard result."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_wizard_stored_github
from yoke_cli.config.onboard_destinations import matches_stored_hosted_authority as _matches_hosted
from yoke_cli.config.onboard_wizard import WizardDefaults


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _stored_yoke_token_available: bool
    _stored_machine_github_api_url: str | None
    _stored_project_checkouts: list[machine_config.ConfiguredProject]


class StoredConnectionHydration:
    def _hydrate_stored_credentials(self: _Shell, defaults: WizardDefaults) -> None:
        """Preload reusable token-file references from machine config.

        The wizard still verifies every secret before using it. This only saves
        the operator from re-entering file paths already recorded in the machine
        config. Project checkouts are also only preloaded here; the Project step
        verifies the stored project id with the API before reusing one.
        """

        self._hydrate_stored_yoke_connection(defaults)
        self._hydrate_stored_github_connection()
        self._hydrate_stored_project_checkouts()

    def _hydrate_stored_yoke_connection(self: _Shell, defaults: WizardDefaults) -> None:
        if defaults.token or defaults.token_file:
            return
        try:
            connection = machine_config.active_connection(
                self.result.config_path,
                explicit_env=defaults.env_name,
            )
        except (OSError, RuntimeError, ValueError):
            return
        if str(connection.get("transport") or "") != "https":
            return
        api_url = str(connection.get("api_url") or "").strip()
        if not api_url:
            return
        if defaults.api_url and not _matches_hosted(defaults.api_url, api_url):
            return
        source = connection.get("credential_source")
        if not isinstance(source, dict) or source.get("kind") != "token_file":
            return
        token_file = str(source.get("path") or "").strip()
        if not token_file:
            return
        token_path = Path(token_file).expanduser()
        if not token_path.is_file():
            return
        self.result.env_name = str(connection.get("env") or self.result.env_name)
        self.result.api_url = api_url
        self.result.token_file = str(token_path)
        self.result.token_source_kind = "token_file"
        self._stored_yoke_token_available = True

    def _hydrate_stored_github_connection(self: _Shell) -> None:
        api_url = onboard_wizard_stored_github.stored_api_url(
            self.result.config_path
        )
        if api_url is None:
            return
        self.result.machine_github_saved = True
        self._stored_machine_github_api_url = api_url

    def _hydrate_stored_project_checkouts(self: _Shell) -> None:
        try:
            self._stored_project_checkouts = machine_config.configured_projects(
                self.result.config_path,
                existing_only=True,
            )
        except (OSError, RuntimeError, ValueError):
            self._stored_project_checkouts = []


__all__ = ["StoredConnectionHydration"]
