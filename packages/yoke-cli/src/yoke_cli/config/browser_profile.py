"""Machine-local persistent browser profile, one directory per project.

An agent must never complete a sign-in, so the signed-in state a Browser case
or an exploratory walker needs has to come from the operator. ``yoke browser
authorize`` opens one project's profile in a plain window of the browser
daemon's own Chromium; whatever the operator signs into there is signed in for
every worker context that daemon later hands out for that project. The window
is a directly spawned browser process rather than an automated one, because
identity providers refuse to sign a human into an automation-controlled
browser.

The profile holds live session cookies, so it lives beside the project's other
machine-local capability secrets with owner-only permissions -- never in the
database, the repository, QA artifacts, or a transcript.

A project that was never authorized simply has no profile directory. That is
not an error: the daemon falls back to a clean throwaway context, exactly as it
behaved before profiles existed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from yoke_contracts.machine_config import capability_secrets as contract
from yoke_contracts.machine_config import schema as machine_contract
from yoke_contracts.project_defaults import default_project_for_directory

from yoke_cli.config import machine_config
from yoke_cli.config.capability_secrets import ensure_private_capability_dir
from yoke_cli.config.project_slug_lookup import resolve_project_slug


def profile_project_key(
    project: str | None = None,
    *,
    directory: Path | None = None,
) -> str:
    """Resolve the directory component naming one project's profile.

    Every caller -- ``yoke browser authorize`` and each daemon-start path --
    resolves the key through this one function, so the profile the operator
    signs into is the profile a worker context later opens. An explicit
    project reference wins; otherwise the checkout answers, the same way every
    other project-accepting surface defaults.

    The reference is canonicalized to the project slug before it names a
    directory, because the two sides are handed different references for the
    same project: ``yoke browser authorize --project yoke`` gets the slug an
    operator typed, while a daemon started from the checkout default gets the
    numeric project id. Keyed by whatever each was handed, they named two
    directories for one project and a signed-in run silently opened a clean
    context. A slug is already canonical; an id-shaped reference resolves
    through the control plane.
    """
    ref = str(project or "").strip()
    if not ref:
        ref = default_project_for_directory(directory or Path.cwd())
    if ref.isdigit():
        ref = resolve_project_slug(ref)
    return contract.safe_secret_component(ref, "project")


def profile_dir(
    project: str | None = None,
    *,
    directory: Path | None = None,
) -> Path:
    """Return the profile directory for a project, whether or not it exists."""
    return (
        machine_config.yoke_home()
        / machine_contract.SECRETS_DIR_NAME
        / contract.browser_profile_relative_path(
            profile_project_key(project, directory=directory)
        )
    )


def authorized_profile_dir(
    project: str | None = None,
    *,
    directory: Path | None = None,
) -> Path | None:
    """Return the profile directory only once the operator has authorized it."""
    candidate = profile_dir(project, directory=directory)
    return candidate if candidate.is_dir() else None


def ensure_profile_dir(
    project: str | None = None,
    *,
    directory: Path | None = None,
) -> Path:
    """Create the project's profile directory with owner-only permissions."""
    return ensure_private_capability_dir(profile_dir(project, directory=directory))


def authorized_project_keys() -> list[str]:
    """List the project slugs that already carry an authorized profile.

    A profile signed in under one project key and looked for under another is
    otherwise a silent miss -- the run proceeds signed out and grades the
    dashboard untestable. Callers name these keys when the profile they wanted
    is absent, so the operator sees which reference to pass. A key that is not
    a slug is a directory no live reference resolves to any more.
    """
    root = (
        machine_config.yoke_home()
        / machine_contract.SECRETS_DIR_NAME
        / contract.CAPABILITY_SECRETS_DIR_NAME
    )
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if (
            entry
            / contract.BROWSER_CONTROL_CAPABILITY
            / contract.BROWSER_PROFILE_DIR_NAME
        ).is_dir()
    )


def resolve_authorized_profile(
    project: str | None = None,
    *,
    directory: Path | None = None,
) -> tuple[Path | None, str]:
    """Resolve a project's profile and one line saying what was resolved.

    An unauthorized project is not a refusal — it gets a clean throwaway
    context, exactly as before profiles existed. It IS worth naming, because a
    profile authorized under a different project reference is otherwise a
    silent miss: the run proceeds signed out and grades every
    dashboard-rendered criterion untestable. So when this project has no
    profile and other projects do, the line says which references do have one.
    """
    key = profile_project_key(project, directory=directory)
    authorized = authorized_profile_dir(project, directory=directory)
    if authorized is not None:
        return authorized, f"Browser profile for project {key}: {authorized}"
    others = [name for name in authorized_project_keys() if name != key]
    if others:
        detail = (
            f" Authorized profiles exist for: {', '.join(others)}."
            " Pass the project reference whose profile you meant, or run"
            f" `yoke browser authorize --project {key}` to sign in for this one."
            " Every profile is keyed by the project slug, so a key that is not"
            " one belongs to no project any more: nothing resolves to it and"
            " nothing reads it."
        )
    else:
        detail = (
            " Sign in once with `yoke browser authorize"
            f" --project {key}` if a case needs an authenticated page."
        )
    return None, f"No browser profile for project {key}; using a clean context.{detail}"


def remove_profile_dir(
    project: str | None = None,
    *,
    directory: Path | None = None,
) -> Path | None:
    """Delete one project's profile directory, and say which one was deleted.

    The path is resolved here rather than accepted from the caller, so the
    only directory this can ever delete is the profile of the project named.
    A project with no profile yet is not an error -- there is simply nothing
    to remove, reported as ``None``.
    """
    target = profile_dir(project, directory=directory)
    if not target.is_dir():
        return None
    shutil.rmtree(target)
    return target


def profile_dir_display(directory: Path) -> str:
    """Render a profile path as an operator reads it: ``~``-relative."""
    try:
        return f"~/{directory.relative_to(Path.home())}"
    except (OSError, ValueError):
        return str(directory)


__all__ = [
    "authorized_profile_dir",
    "authorized_project_keys",
    "ensure_profile_dir",
    "profile_dir",
    "profile_dir_display",
    "profile_project_key",
    "remove_profile_dir",
    "resolve_authorized_profile",
]
