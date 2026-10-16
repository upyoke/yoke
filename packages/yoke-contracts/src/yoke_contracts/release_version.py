"""One commit-clock version for wheels, tags, images and display."""

from __future__ import annotations

from datetime import datetime, timezone
import re

BASE_VERSION = "0.2.0"
_BASE = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
_VERSION = re.compile(rf"({_BASE})\.([1-9][0-9]{{7}})([0-9]{{4}})")


def commit_version(committed_at: datetime, *, base: str = BASE_VERSION) -> str:
    """Derive a release name from the commit clock, never the build clock."""
    if committed_at.tzinfo is None or not re.fullmatch(_BASE, base):
        raise ValueError(
            "release_identity_invalid: use an aware commit time and X.Y.Z base"
        )
    return f"{base}.{committed_at.astimezone(timezone.utc):%Y%m%d%H%M}"


def release_version(value: str) -> str:
    """Require the identical canonical spelling at every release boundary."""
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ValueError(
            "release_version_invalid: use BASE.YYYYMMDDHHMM from the commit UTC time"
        )
    base, date, time = match.groups()
    try:
        datetime.strptime(date + time, "%Y%m%d%H%M")
    except ValueError as exc:
        raise ValueError(
            "release_version_invalid: use a valid UTC commit date and minute"
        ) from exc
    return f"{base}.{date}{time}"


def version_order(value: str) -> tuple[tuple[int, ...], int, int]:
    """Base-version ordering followed by the immutable commit clock."""
    match = _VERSION.fullmatch(release_version(value))
    assert match is not None
    base, date, time = match.groups()
    return tuple(map(int, base.split("."))), int(date), int(time)
