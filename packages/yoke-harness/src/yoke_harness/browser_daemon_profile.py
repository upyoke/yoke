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


def process_matches_start(pid: int, expected: str | None) -> bool:
    """Keep shutdown scoped to the recorded process through pid reuse."""
    if expected is None:
        return True
    from yoke_contracts.process_ancestry import process_start_time

    return process_start_time(pid) == expected


@contextmanager
def profile_scope(profile_dir: str | Path | None):
    """Route every call in one capture to its profile; restore on all exits."""
    token = _selected_profile.set(canonical_profile(profile_dir))
    try:
        yield
    finally:
        _selected_profile.reset(token)


def state_file_path(runtime_dir: Path, profile_dir: str | None = None) -> Path:
    profile = (
        selected_profile() if profile_dir is None else canonical_profile(profile_dir)
    )
    key = hashlib.sha256(profile.encode()).hexdigest() if profile else "throwaway"
    return runtime_dir / "daemons" / key / ".daemon-state.json"
