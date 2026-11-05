# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

from yoke_cli.config import machine_config

from yoke_cli.config import onboard_existing_project

from yoke_cli.config import project_installed_layer as layer

from yoke_cli.config.onboard_wizard_checkout_inspection_screen import (
    LAYER_ROWS,
    inspection_prompt,
)

from yoke_cli.config.onboard_wizard_existing_project_detected import (
    CHOICE_CONNECT,
    CHOICE_DETAILS,
    CHOICE_NEW_PROJECT,
    DETECTED_ROWS,
    ExistingProjectDetectedFlow,
)

from yoke_cli.config.onboard_wizard_stored_project import StoredProjectFlow

from yoke_cli.config.onboard_wizard_widgets import SelectionList

from yoke_cli.config.setup_prompt import TONE_ERROR

from runtime.api.cli.onboard_checkout_inspection_fixtures import (
    repo_with_layer as _repo_with_layer,
)


class _DetectionShell(ExistingProjectDetectedFlow):
    """The routing surface the detection screen's two answers reach."""

    def __init__(self) -> None:
        self.result = SimpleNamespace(
            existing_project_id=7,
            existing_project_match_source="github_repo",
            existing_project_local_source=None,
            project_slug="buzz",
            project_name="Buzz",
            project_default_branch="main",
            project_public_item_prefix="BZZ",
            project_github_adoption="app_binding",
            project_github_adoption_preserve=True,
        )
        self.announced: list[object] = []
        self.continued = 0
        self.slug_prompts = 0
        self.folder_prompts = 0
        self.destination_prompts = 0

    def _goto_existing_project_ready(self, *, on_choice=None) -> None:
        self.announced.append(on_choice)

    def _after_existing_project_ready(self) -> None:
        self.continued += 1

    def _goto_project_details(self) -> None:
        self.slug_prompts += 1

    def _goto_checkout_destination(self) -> None:
        self.destination_prompts += 1

    def _goto_clone_folder(self) -> None:
        self.folder_prompts += 1
