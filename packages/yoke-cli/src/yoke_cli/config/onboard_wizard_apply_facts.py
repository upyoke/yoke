"""What Apply is about to create, recorded as it starts, and the checks that read it.

Apply creates the local universe, the project folder, the machine's checkout
registration and the Yoke project. When Apply fails and setup goes back — the
wizard's Change answers, or agent mode replaying its stored answers on the
next call — the Project and Account screens would find those and take a
different route: an existing universe, a folder that "already exists", a saved
checkout to pick, a project that "already exists". Each fact here names one
thing this run's Apply made, so those screens see the world the person
answered in. Facts are recorded before the worker starts, since a failed step
may still have made its change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import local_universe_setup, machine_config, onboard_project
from yoke_cli.config.onboard_destinations import DESTINATION_LOCAL
from yoke_cli.config.project_publish_support import is_existing_project_dir
from yoke_cli.config.setup_run_facts import (
    APPLY_NEW_FOLDER,
    APPLY_NEW_PROJECT,
    APPLY_NEW_REGISTRATION,
    LOCAL_UNIVERSE_CREATED,
    checkout_key,
)


def record(shell: Any) -> None:
    """Record what this Apply creates; a fact already recorded stays."""
    result, facts = shell.result, shell._run_facts
    if result.destination == DESTINATION_LOCAL and not facts.get(
        LOCAL_UNIVERSE_CREATED
    ):
        state = local_universe_setup.inspect_local_state(result.config_path)
        if state.get("state") == local_universe_setup.LOCAL_UNIVERSE_CREATE:
            facts.record(LOCAL_UNIVERSE_CREATED, True)
    checkout = result.project_checkout
    if not checkout or result.project_mode == onboard_project.PROJECT_MODE_MACHINE_ONLY:
        return
    root = checkout_key(checkout)
    if not is_existing_project_dir(Path(root)):
        facts.record(APPLY_NEW_FOLDER, root)
    if root not in _registered_checkouts(result.config_path):
        facts.record(APPLY_NEW_REGISTRATION, root)
    if not result.existing_project_id and result.project_slug:
        facts.record(APPLY_NEW_PROJECT, result.project_slug)


def own_project(shell: Any, project: Any) -> bool:
    """True when a looked-up project is the one this run's Apply created."""
    slug = shell._run_facts.get(APPLY_NEW_PROJECT)
    return bool(slug) and getattr(project, "slug", None) == slug


def own_project_reference(shell: Any, checkout: str) -> bool:
    """True when ``checkout``'s project reference was written by this run's Apply."""
    facts = shell._run_facts
    return bool(facts.get(APPLY_NEW_PROJECT)) and facts.names_folder(
        APPLY_NEW_REGISTRATION, checkout
    )


def own_folder(shell: Any, folder: str) -> bool:
    """True when ``folder`` did not exist until this run's Apply."""
    return shell._run_facts.names_folder(APPLY_NEW_FOLDER, folder)


def without_own_registration(shell: Any, projects: list[Any]) -> list[Any]:
    """Saved checkouts, minus the one this run's Apply registered."""
    facts = shell._run_facts
    return [
        project
        for project in projects
        if not facts.names_folder(APPLY_NEW_REGISTRATION, project.checkout)
    ]


def without_own_folder(shell: Any, folders: list[Any]) -> list[Any]:
    """Detected checkouts, minus the folder this run's Apply created."""
    return [folder for folder in folders if not own_folder(shell, folder)]


def _registered_checkouts(config_path: str) -> set[str]:
    try:
        projects = machine_config.configured_projects(config_path)
    except (OSError, RuntimeError, ValueError):
        return set()
    return {checkout_key(project.checkout) for project in projects}


__all__ = [
    "own_folder",
    "own_project",
    "own_project_reference",
    "record",
    "without_own_folder",
    "without_own_registration",
]
