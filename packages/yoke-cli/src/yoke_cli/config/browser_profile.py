"""Machine-local persistent browser profiles, one per project identity.

``yoke browser authorize`` signs declared automatic first-party test accounts
in headless from machine-local secret files. Human sites open in a plain
window of the daemon's Chromium, because some identity providers refuse
automation-controlled sign-in. Both paths save the authoritative identity
profile; QA checks copy its sign-in state into private profiles and daemons.
Agents never read credential values.

A project declares named identities (``yoke_contracts.browser_identity``);
each has its own profile, so signing a second account in never overwrites the
first. The ``default`` identity is the project's original single profile.

The profile holds live session cookies, so it stays machine-local with
owner-only permissions -- never in the database, the repository, QA
artifacts, or a transcript.

Every identity profile lives in the machine's live identity store,
``~/.yoke-browser-identities/<project>/<identity>``
(``LIVE_IDENTITY_STORE_HOME_ENTRY``), outside ``~/.yoke``. A Test Machine's
full reset deletes ``~/.yoke`` but keeps that store, so the installed product
reads and refreshes the live profile in place and nothing is ever restored
from a stale copy. The store is created owner-only the first time a profile is
created; a store that is a link, not a directory, or cannot be created refuses
by name, because a profile saved anywhere else would vanish at the next reset.
A profile signed in at the old capability-secret path under ``~/.yoke`` is
moved into the store the first time its identity is used, not discarded.

An identity that was never authorized simply has no profile directory. That is
not an error: its QA check starts with a clean private profile.
"""

from __future__ import annotations

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


def _legacy_profile_path(key: str, identity: str) -> Path:
    return (
        machine_config.yoke_home()
        / machine_contract.SECRETS_DIR_NAME
        / contract.browser_profile_relative_path(key, identity)
    )


def live_identity_store_root() -> Path:
    """This machine's live identity store, a sibling of the machine home."""
    return machine_config.yoke_home().parent / LIVE_IDENTITY_STORE_HOME_ENTRY


def _store_unusable(root: Path, reason: str) -> BrowserIdentityError:
    return BrowserIdentityError(
        f"browser_identity_store_unavailable: the live identity store {root} "
        f"{reason}. A profile saved anywhere else is deleted by the next test "
        f"machine reset. Make {root} an owner-only directory (not a link) "
        "owned by this user, then retry."
    )


def _usable_store_root(*, create: bool) -> Path | None:
    """Return the store root, creating it when ``create`` is set.

    An absent store on a read is not an error: no identity was authorized yet.
    """
    root = live_identity_store_root()
    if root.is_symlink():
        raise _store_unusable(root, "is a link")
    if root.exists() and not root.is_dir():
        raise _store_unusable(root, "is not a directory")
    if not root.exists():
        if not create:
            return None
        try:
            create_private_directory(root)
        except OSError as exc:
            raise _store_unusable(root, f"could not be created ({exc})") from None
    return root


def _profile_path(key: str, identity: str) -> Path:
    return live_identity_store_root().parent / live_identity_store_relative_path(
        key, identity
    )


def _adopt_legacy_profile(key: str, identity: str) -> None:
    """Move a profile signed in under ``~/.yoke`` into the live store.

    A link left there by an earlier release pointed into the store already and
    is removed. A real directory is the only copy of that sign-in, so it is
    moved, never replaced; a profile in both places refuses by name.
    """
    legacy = _legacy_profile_path(key, identity)
    if legacy.is_symlink():
        legacy.unlink()
        return
    if not legacy.is_dir():
        return
    target = _profile_path(key, identity)
    if target.exists():
        raise BrowserIdentityError(
            "browser_identity_store_conflict: identity "
            f"{identity!r} of project {key!r} has a profile both at {legacy} "
            f"and in the live store at {target}. Keep the one that is "
            "signed in and delete the other, then retry."
        )
    _usable_store_root(create=True)
    try:
        create_private_directory(target.parent)
        shutil.move(str(legacy), str(target))
    except OSError as exc:
        raise _store_unusable(
            live_identity_store_root(),
            f"could not take the profile at {legacy} ({exc})",
        ) from None


def _resolve(key: str, identity: str, *, create: bool) -> Path:
    _usable_store_root(create=False)
    _adopt_legacy_profile(key, identity)
    path = _profile_path(key, identity)
    if create:
        _usable_store_root(create=True)
        try:
            create_private_directory(path)
        except OSError as exc:
            raise _store_unusable(
                live_identity_store_root(), f"could not hold {path} ({exc})"
            ) from None
    return path


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
    candidate = _resolve(key, identity, create=False)
    return candidate if candidate.is_dir() else None


def ensure_profile_dir(
    project: str | None = None,
    *,
    identity: str = DEFAULT_IDENTITY,
    directory: Path | None = None,
) -> Path:
    """Create the identity's profile in the live store, creating the store too."""
    key = profile_project_key(project, directory=directory)
    return _resolve(key, identity, create=True)


def authorized_project_keys() -> list[str]:
    """List the project slugs that already carry an authorized default profile.

    A profile signed in under one project key and looked for under another is
    otherwise a silent miss -- the run proceeds signed out and grades the
    dashboard untestable. Callers name these keys when the profile they wanted
    is absent, so the operator sees which reference to pass. A key that is not
    a slug is a directory no live reference resolves to any more.
    """
    root = _usable_store_root(create=False)
    if root is None:
        return []
    return sorted(
        entry.name for entry in root.iterdir() if (entry / DEFAULT_IDENTITY).is_dir()
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
    only directory this can ever delete is the named identity's profile in the
    live store. An identity with no profile yet is not an error -- there is
    simply nothing to remove, reported as ``None``.
    """
    key = profile_project_key(project, directory=directory)
    target = _resolve(key, identity, create=False)
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
    "live_identity_store_root",
    "profile_dir",
    "profile_dir_display",
    "profile_project_key",
    "remove_profile_dir",
    "resolve_authorized_profile",
]
