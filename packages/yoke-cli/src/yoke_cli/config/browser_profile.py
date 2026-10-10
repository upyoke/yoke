"""Machine-local persistent browser profiles, one per project identity.

An agent must never complete a sign-in, so the signed-in state a Browser case
or an exploratory walker needs has to come from the operator. ``yoke browser
authorize`` opens one identity's profile in a plain window of the browser
daemon's own Chromium; whatever the operator signs into there is signed in for
every worker context that daemon later hands out for that identity. The window
is a directly spawned browser process rather than an automated one, because
identity providers refuse to sign a human into an automation-controlled
browser.

A project declares named identities (``yoke_contracts.browser_identity``);
each has its own profile, so signing a second account in never overwrites the
first. The ``default`` identity is the project's original single profile.

The profile holds live session cookies, so it lives beside the project's other
machine-local capability secrets with owner-only permissions -- never in the
database, the repository, QA artifacts, or a transcript.

A Test Machine keeps its live identities in a store outside ``~/.yoke`` that a
full reset preserves (``LIVE_IDENTITY_STORE_HOME_ENTRY``). On such a machine an
identity's profile path is a link into that store, so the installed product
reads and refreshes the live profile in place and nothing is ever restored
from a stale copy. A profile already signed in at the capability path when the
store is first used is moved into the store, not discarded.

An identity that was never authorized simply has no profile directory. That is
not an error: the daemon falls back to a clean throwaway context, exactly as it
behaved before profiles existed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from yoke_contracts.browser_identity import (
    DEFAULT_IDENTITY,
    LIVE_IDENTITY_STORE_HOME_ENTRY,
    BrowserIdentityError,
    live_identity_store_relative_path,
)
from yoke_contracts.machine_config import capability_secrets as contract
from yoke_contracts.machine_config import schema as machine_contract
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_cli.config.project_selection import required_project_context

from yoke_cli.config import machine_config
from yoke_cli.config.capability_secrets import ensure_private_capability_dir
from yoke_cli.config.project_slug_lookup import resolve_project_slug


def profile_project_key(
    project: str | None = None,
    *,
    directory: Path | None = None,
) -> str:
    """Resolve the directory component naming one project's profiles.

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
    ref = required_project_context(project, directory=directory)
    if ref.isdigit():
        ref = resolve_project_slug(ref)
    return contract.safe_secret_component(ref, "project")


def _profile_path(key: str, identity: str) -> Path:
    return (
        machine_config.yoke_home()
        / machine_contract.SECRETS_DIR_NAME
        / contract.browser_profile_relative_path(key, identity)
    )


def live_identity_store_root() -> Path | None:
    """This machine's live identity store, or ``None`` when it keeps none."""
    root = machine_config.yoke_home().parent / LIVE_IDENTITY_STORE_HOME_ENTRY
    return root if root.is_dir() and not root.is_symlink() else None


def _link_live_identity(key: str, identity: str, *, create: bool) -> None:
    """Point an identity's profile path at its live store entry, if any.

    The store entry is created only when ``create`` is set (an authorize is
    about to sign it in); a read never invents one. A real profile directory
    found at the capability path while the store has none for this identity
    is adopted into the store, so a sign-in made before the store existed is
    kept rather than replaced.
    """
    root = live_identity_store_root()
    if root is None:
        return
    target = root.parent / live_identity_store_relative_path(key, identity)
    link = _profile_path(key, identity)
    if link.is_symlink():
        if Path(os.readlink(link)) == target:
            if create:
                create_private_directory(target)
            return
        link.unlink()
    elif link.is_dir():
        if target.exists():
            raise BrowserIdentityError(
                "browser_identity_store_conflict: identity "
                f"{identity!r} of project {key!r} has a profile both at {link} "
                f"and in the live store at {target}. Keep the one that is "
                "signed in and delete the other, then retry."
            )
        create_private_directory(target.parent)
        shutil.move(str(link), str(target))
    elif create:
        create_private_directory(target)
    if not target.is_dir():
        return
    ensure_private_capability_dir(link.parent)
    link.symlink_to(target, target_is_directory=True)


def profile_dir(
    project: str | None = None,
    *,
    identity: str = DEFAULT_IDENTITY,
    directory: Path | None = None,
) -> Path:
    """Return one identity's profile directory, whether or not it exists."""
    return _profile_path(profile_project_key(project, directory=directory), identity)


def authorized_profile_dir(
    project: str | None = None,
    *,
    identity: str = DEFAULT_IDENTITY,
    directory: Path | None = None,
) -> Path | None:
    """Return the identity's profile directory once the operator authorized it."""
    key = profile_project_key(project, directory=directory)
    _link_live_identity(key, identity, create=False)
    candidate = _profile_path(key, identity)
    return candidate if candidate.is_dir() else None


def ensure_profile_dir(
    project: str | None = None,
    *,
    identity: str = DEFAULT_IDENTITY,
    directory: Path | None = None,
) -> Path:
    """Create the identity's profile directory with owner-only permissions."""
    key = profile_project_key(project, directory=directory)
    _link_live_identity(key, identity, create=True)
    path = _profile_path(key, identity)
    if path.is_symlink():
        return path
    return ensure_private_capability_dir(path)


def authorized_project_keys() -> list[str]:
    """List the project slugs that already carry an authorized default profile.

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
    identity: str = DEFAULT_IDENTITY,
    directory: Path | None = None,
) -> tuple[Path | None, str]:
    """Resolve an identity's profile and one line saying what was resolved.

    An unauthorized identity is not a refusal — it gets a clean throwaway
    context, exactly as before profiles existed. It IS worth naming, because a
    profile authorized under a different project reference is otherwise a
    silent miss: the run proceeds signed out and grades every
    dashboard-rendered criterion untestable. So when this project has no
    profile and other projects do, the line says which references do have one.
    """
    key = profile_project_key(project, directory=directory)
    authorized = authorized_profile_dir(key, identity=identity)
    label = f"project {key} identity {identity}"
    if authorized is not None:
        return authorized, f"Browser profile for {label}: {authorized}"
    sign_in = f"`yoke browser authorize --project {key} --identity {identity}`"
    others = [name for name in authorized_project_keys() if name != key]
    if identity == DEFAULT_IDENTITY and others:
        detail = (
            f" Authorized profiles exist for: {', '.join(others)}."
            " Pass the project reference whose profile you meant, or run"
            f" {sign_in} to sign in for this one."
            " Every profile is keyed by the project slug, so a key that is not"
            " one belongs to no project any more: nothing resolves to it and"
            " nothing reads it."
        )
    else:
        detail = f" Sign in once with {sign_in} if a case needs an authenticated page."
    return None, f"No browser profile for {label}; using a clean context.{detail}"


def remove_profile_dir(
    project: str | None = None,
    *,
    identity: str = DEFAULT_IDENTITY,
    directory: Path | None = None,
) -> Path | None:
    """Delete one identity's profile, and say which one was deleted.

    The path is resolved here rather than accepted from the caller, so the
    only directory this can ever delete is the named identity's profile. On a
    machine with a live identity store the store entry is what holds the
    sign-in, so it is deleted with the link. An identity with no profile yet
    is not an error -- there is simply nothing to remove, reported as ``None``.
    """
    key = profile_project_key(project, directory=directory)
    _link_live_identity(key, identity, create=False)
    target = _profile_path(key, identity)
    if not target.is_dir():
        return None
    if target.is_symlink():
        shutil.rmtree(target.resolve())
        target.unlink()
    else:
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
    "live_identity_store_root",
    "profile_dir",
    "profile_dir_display",
    "profile_project_key",
    "remove_profile_dir",
    "resolve_authorized_profile",
]
