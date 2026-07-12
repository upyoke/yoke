"""Routing for project checkouts already registered on this machine."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT, SelectionRow
from yoke_cli.project_install import source_dev

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


def _is_yoke_source_checkout(path: Path) -> bool:
    try:
        return source_dev.is_yoke_source_checkout(path.expanduser())
    except OSError:
        return False


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _pending_stored_project_checkout: str | None
    _preset_dev_checkout: str | None
    _stored_project_checkouts: list[machine_config.ConfiguredProject]

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_project_mode(self) -> None: ...
    def _on_project_mode(self, mode: str) -> None: ...
    def _check_project_git(self, mode: str) -> None: ...


class StoredProjectFlow:
    """Offer, validate, and route a saved project checkout mapping."""

    def _goto_stored_project_picker(self: _Shell) -> None:
        rows: list[SelectionRow] = []
        for index, project in enumerate(self._stored_project_checkouts):
            checkout = str(project.checkout)
            rows.append(SelectionRow(
                f"stored:{index}", checkout, f"project id {project.project_id}",
            ))
            if _is_yoke_source_checkout(project.checkout):
                rows.append(SelectionRow(
                    f"source-dev:{index}",
                    "Develop Yoke itself",
                    f"use {checkout} as the source checkout",
                ))
        rows.extend((
            SelectionRow(
                "other", "Choose another project", "show all project options",
            ),
            SelectionRow(
                "none", "Don't set up a project now", "just the machine",
            ),
        ))
        self._goto(self._selection_view(
            STEP_PROJECT,
            "Use an existing project mapping?",
            "Yoke found project mappings saved on this machine. Reuse one, or "
            "choose another path.",
            rows,
            self._on_stored_project_choice,
        ))

    def _on_stored_project_choice(self: _Shell, choice: str) -> None:
        if choice == "other":
            self._goto_project_mode()
            return
        if choice == "none":
            self._on_project_mode(onboard_project.PROJECT_MODE_MACHINE_ONLY)
            return
        if choice.startswith("source-dev:"):
            project = self._selected_stored_project(choice)
            if project is None:
                self._goto_project_mode()
                return
            steps.reset_project_fields(self.result)
            self._preset_dev_checkout = str(project.checkout)
            self.result.project_checkout = str(project.checkout)
            self._on_project_mode(onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN)
            return
        if choice.startswith("stored:"):
            project = self._selected_stored_project(choice)
            if project is not None:
                self._use_stored_project_checkout(project)
                return
        self._goto_project_mode()

    def _selected_stored_project(
        self: _Shell, choice: str,
    ) -> machine_config.ConfiguredProject | None:
        try:
            return self._stored_project_checkouts[int(choice.split(":", 1)[1])]
        except (IndexError, TypeError, ValueError):
            return None

    def _use_stored_project_checkout(
        self: _Shell,
        project: machine_config.ConfiguredProject,
    ) -> None:
        checkout = str(project.checkout)
        steps.reset_project_fields(self.result)
        self.result.project_mode = onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
        self.result.project_checkout = checkout
        self._pending_stored_project_checkout = checkout
        self._check_project_git(onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)


__all__ = ["StoredProjectFlow"]
