"""Profile-scoped routing for browser daemon state and transport calls."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_selected_profile: ContextVar[str] = ContextVar("browser_daemon_profile", default="")


def canonical_profile(profile_dir: str | Path | None) -> str:
    return str(Path(profile_dir).expanduser().resolve()) if profile_dir else ""


def selected_profile() -> str:
    return _selected_profile.get()


@contextmanager
def profile_scope(profile_dir: str | Path | None):
    """Route every call in one capture to its profile; restore on all exits."""
    token = _selected_profile.set(canonical_profile(profile_dir))
    try:
        yield
    finally:
        _selected_profile.reset(token)


@contextmanager
def project_scope(project: str | None, identity: str | None = None):
    """Route calls to one project identity's daemon (``default`` when omitted)."""
    from yoke_contracts.browser_identity import DEFAULT_IDENTITY
    from yoke_cli.config.browser_profile import authorized_profile_dir

    with profile_scope(
        authorized_profile_dir(project, identity=identity or DEFAULT_IDENTITY)
    ):
        yield


def state_file_path(runtime_dir: Path, profile_dir: str | None = None) -> Path:
    profile = (
        selected_profile() if profile_dir is None else canonical_profile(profile_dir)
    )
    key = hashlib.sha256(profile.encode()).hexdigest() if profile else "throwaway"
    return runtime_dir / "daemons" / key / ".daemon-state.json"


def recover_unhealthy_daemon(client, profile_dir: str | None) -> None:
    """Retry cleanup can stop only an unhealthy process belonging to this profile."""
    profile = canonical_profile(profile_dir)
    state = client.DaemonState.load(client._state_file_path(profile))
    if state is None or not client.daemon_running(state):
        return
    if canonical_profile(state.profile_dir) != profile:
        raise RuntimeError(
            "browser_daemon_profile_mismatch: state belongs to another profile; "
            "inspect this profile's state file and rerun `yoke qa browser setup`"
        )
    try:
        client.daemon_health(state=state, timeout=1)
    except RuntimeError:
        client.daemon_stop(profile_dir=profile)
