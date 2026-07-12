"""Progress callback helpers for ``yoke onboard`` apply."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterable, Iterator

from yoke_cli.config.onboard_project_modes import (
    PROJECT_MODE_CLONE_REMOTE,
    PROJECT_MODE_CREATE_REPO,
    PROJECT_MODE_IMPORT_REMOTE,
    PROJECT_MODE_LOCAL_CHECKOUT,
    PROJECT_MODE_SOURCE_DEV_ADMIN,
)

ProgressCallback = Callable[[str, str, str], None]


def emit(
    progress: ProgressCallback | None,
    action: str,
    target: str,
    status: str,
) -> None:
    if progress is not None:
        progress(action, target, status)


def emit_many(
    progress: ProgressCallback | None,
    steps: Iterable[tuple[str, str]],
    status: str,
) -> None:
    for action, target in steps:
        emit(progress, action, target, status)


@contextmanager
def step(
    progress: ProgressCallback | None,
    action: str,
    target: str = "",
) -> Iterator[None]:
    emit(progress, action, target, "running")
    try:
        yield
    except Exception:
        emit(progress, action, target, "failed")
        raise
    emit(progress, action, target, "done")


def project_action_for_mode(project_mode: str) -> str:
    if project_mode == PROJECT_MODE_CREATE_REPO:
        return "project-create-checkout"
    if project_mode == PROJECT_MODE_CLONE_REMOTE:
        return "project-clone-remote"
    if project_mode == PROJECT_MODE_IMPORT_REMOTE:
        return "project-import-remote"
    if project_mode == PROJECT_MODE_LOCAL_CHECKOUT:
        return "project-onboard-local-checkout"
    if project_mode == PROJECT_MODE_SOURCE_DEV_ADMIN:
        return "project-source-dev-admin"
    return "project-onboard"


__all__ = ["ProgressCallback", "emit", "emit_many", "project_action_for_mode", "step"]
