"""Project-mode vocabulary and validation for product onboarding."""

from __future__ import annotations


DEFAULT_NEW_REPO_BRANCH = "main"
DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT = "existing-project"
DEFAULT_BRANCH_SOURCE_SOURCE_REPO = "source-repo"
DEFAULT_BRANCH_SOURCE_SOURCE_FALLBACK = "source-fallback"

PROJECT_MODE_MACHINE_ONLY = "machine-only"
PROJECT_MODE_CREATE_REPO = "create-repo"
PROJECT_MODE_CLONE_REMOTE = "clone-remote"
PROJECT_MODE_IMPORT_REMOTE = "import-remote"
PROJECT_MODE_LOCAL_CHECKOUT = "local-checkout"
PROJECT_MODE_SOURCE_DEV_ADMIN = "source-dev-admin"
PROJECT_REMOTE_MODES = (PROJECT_MODE_CLONE_REMOTE, PROJECT_MODE_IMPORT_REMOTE)
PROJECT_MODES = (
    PROJECT_MODE_MACHINE_ONLY,
    PROJECT_MODE_CREATE_REPO,
    PROJECT_MODE_CLONE_REMOTE,
    PROJECT_MODE_IMPORT_REMOTE,
    PROJECT_MODE_LOCAL_CHECKOUT,
    PROJECT_MODE_SOURCE_DEV_ADMIN,
)


# Modes that onboard a project Yoke will deploy for, and so the modes offered a
# hosting credential. Machine-only has no project to own one; developing Yoke
# itself runs through `yoke dev setup` and deploys nothing of its own.
PROJECT_DEPLOYABLE_MODES = tuple(
    mode for mode in PROJECT_MODES
    if mode not in (PROJECT_MODE_MACHINE_ONLY, PROJECT_MODE_SOURCE_DEV_ADMIN)
)


class OnboardProjectError(RuntimeError):
    """The project handoff part of onboarding cannot proceed."""


def offers_hosting_credential(project_mode: str | None) -> bool:
    """Whether a run in this mode reaches the hosting-credential step."""
    return (project_mode or "") in PROJECT_DEPLOYABLE_MODES


def normalize_project_mode(project_mode: str | None) -> str:
    selected = (project_mode or PROJECT_MODE_MACHINE_ONLY).strip()
    if selected not in PROJECT_MODES:
        raise OnboardProjectError(
            f"unknown project mode {selected!r}; expected one of "
            f"{', '.join(PROJECT_MODES)}"
        )
    return selected


__all__ = [
    "DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT",
    "DEFAULT_BRANCH_SOURCE_SOURCE_FALLBACK",
    "DEFAULT_BRANCH_SOURCE_SOURCE_REPO",
    "DEFAULT_NEW_REPO_BRANCH",
    "OnboardProjectError",
    "PROJECT_MODE_CLONE_REMOTE",
    "PROJECT_MODE_CREATE_REPO",
    "PROJECT_MODE_IMPORT_REMOTE",
    "PROJECT_MODE_LOCAL_CHECKOUT",
    "PROJECT_MODE_MACHINE_ONLY",
    "PROJECT_MODE_SOURCE_DEV_ADMIN",
    "PROJECT_MODES",
    "PROJECT_DEPLOYABLE_MODES",
    "PROJECT_REMOTE_MODES",
    "normalize_project_mode",
    "offers_hosting_credential",
]
