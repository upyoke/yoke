"""Keep an authorized browser profile's sign-in cookies readable by the daemon.

A site that authenticates with a session cookie -- no ``Max-Age``, no
``Expires`` -- writes a row Chromium discards the next time the profile is
opened, because a profile opened for automation does not restore the previous
session. So the operator's sign-in through ``yoke browser authorize``
evaporated the moment they closed the window, and every worker context the
daemon later opened rendered the site signed out with an empty cookie store.

Chromium offers no switch that changes this for an automated launch: the
profile preference that means "continue where you left off"
(``session.restore_on_startup``) and the ``--restore-last-session`` command
line switch were both measured against a Playwright persistent context and
neither preserved a session cookie. What does survive is a cookie the store
already considers persistent, so between the window closing and the next
launch each session cookie is given an explicit expiry. The value stays
encrypted exactly as Chromium wrote it; only the row's lifetime changes.

That is the whole point of an authorized profile -- it exists to hold one
operator sign-in for later automated runs -- but it is a real extension of a
lifetime the site chose, so it is bounded rather than indefinite.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


SIGN_IN_COOKIE_LIFETIME_DAYS = 30
"""How long a kept sign-in cookie stays valid before the operator signs in again."""

_COOKIE_STORE_RELATIVE_PATH = Path("Default") / "Cookies"

# Chromium stores cookie times as microseconds since 1601-01-01 UTC.
_CHROMIUM_EPOCH_OFFSET_SECONDS = 11_644_473_600


class SignInCookieError(RuntimeError):
    """The profile's cookie store could not be read or updated."""


def cookie_store_path(profile_dir: Path) -> Path:
    """Return the Chromium cookie store inside one profile directory."""
    return Path(profile_dir) / _COOKIE_STORE_RELATIVE_PATH


def keep_sign_in_cookies(
    profile_dir: Path,
    *,
    lifetime_days: int = SIGN_IN_COOKIE_LIFETIME_DAYS,
    now: float | None = None,
) -> int:
    """Give the profile's session cookies an expiry, and return how many.

    Call this while no browser holds the profile -- after the sign-in window
    closes, and before the daemon launches its persistent context. A profile
    that was never signed into has no cookie store yet; that is zero kept
    cookies, not a failure.
    """
    store = cookie_store_path(profile_dir)
    if not store.is_file():
        return 0
    expires_utc = _chromium_timestamp(
        (time.time() if now is None else now) + lifetime_days * 86_400
    )
    try:
        connection = sqlite3.connect(str(store))
    except sqlite3.Error as exc:
        raise SignInCookieError(_unreadable_message(store, exc)) from exc
    try:
        with connection:
            kept = connection.execute(
                "UPDATE cookies SET is_persistent = 1, has_expires = 1, "
                "expires_utc = ? WHERE is_persistent = 0",
                (expires_utc,),
            ).rowcount
    except sqlite3.Error as exc:
        raise SignInCookieError(_unreadable_message(store, exc)) from exc
    finally:
        connection.close()
    return max(kept, 0)


def _chromium_timestamp(epoch_seconds: float) -> int:
    return int((epoch_seconds + _CHROMIUM_EPOCH_OFFSET_SECONDS) * 1_000_000)


def _unreadable_message(store: Path, exc: sqlite3.Error) -> str:
    return (
        f"the browser profile's cookie store at {store} could not be updated "
        f"({exc}). A running browser locks it: close the sign-in window and "
        "stop the daemon with `yoke qa browser stop`, then retry. If the "
        "store is damaged, sign in again from a clean profile with "
        "`yoke browser authorize --reset`."
    )


__all__ = [
    "SIGN_IN_COOKIE_LIFETIME_DAYS",
    "SignInCookieError",
    "cookie_store_path",
    "keep_sign_in_cookies",
]
