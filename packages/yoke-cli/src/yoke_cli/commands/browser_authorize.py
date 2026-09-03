"""``yoke browser authorize`` — the operator signs a project's browser in once.

An agent must never complete a sign-in, so the signed-in state a Browser case
or an exploratory walker needs comes from the operator. This opens the
project's persistent browser profile in a plain window of the browser daemon's
own Chromium — a directly spawned process, not an automation-controlled one —
so identity providers that refuse automated browsers still let the operator
sign in. Whatever they sign into there is signed in for every worker context
the daemon later opens for that project. There are no origin lists,
declarations, per-site probes, or exported storage state — just the profile
the operator used.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config.browser_profile_cookies import (
    SIGN_IN_COOKIE_LIFETIME_DAYS,
    SignInCookieError,
    keep_sign_in_cookies,
)


BROWSER_AUTHORIZE_USAGE = (
    "yoke browser authorize [--project PROJECT] [--url URL] [--reset] [--json]"
)

_BROWSER_AUTHORIZE_HELP_DEEP = """\
Open one project's persistent browser profile in a plain window of the browser
daemon's own Chromium and wait until you close it. Sign into as many sites as
you like; every session the window ends up holding is a session the project's
Browser cases and exploratory walkers get. Nothing is exported, and no
credential is read, stored, or logged by Yoke — the profile is Chromium's own,
kept with the project's machine-local capability secrets at owner-only
permissions.

The window is a directly spawned browser process, never an automated one. An
automation-controlled browser announces itself — `--enable-automation`,
`navigator.webdriver`, an attached debugging session — and Google's sign-in
refuses exactly that shape with "Couldn't sign you in. This browser or app may
not be secure", so a profile opened under automation could not be signed into
through Google at all. It is the daemon's own Chromium binary rather than any
other installed browser, launched with the daemon's own cookie-encryption
switches, because Chromium drops any stored cookie it cannot decrypt when it
opens a profile: a sign-in written in a different key domain -- another
browser, or this one launched differently -- is gone by the time the daemon
looks.

The profile is keyed by the project slug, so a slug, a numeric project id, and
the checkout default all open the one profile for that project.

Worked examples:

  yoke browser authorize                      # the project of this checkout
  yoke browser authorize --project yoke
  yoke browser authorize --url https://app.upyoke.com

The browser daemon is a machine singleton and Chromium locks a profile
directory, so a running daemon is stopped first; the next case run starts it
again on the profile you just signed into.

Sites that authenticate with a session cookie -- one with no expiry, which
an ordinary browser drops when it quits -- would otherwise lose the sign-in
the moment you close this window. So when the window closes, every session
cookie the profile holds is given an explicit {lifetime}-day expiry, and the
count is reported. Sign in again after that, or whenever a walker lands on a
sign-in page: an expired session is already the human gate it raises, and
needs no other machinery.

Start over with a profile that has gone wrong -- a stale sign-in, a site that
will not sign in again, a profile signed into the wrong account:

  yoke browser authorize --reset

That stops the daemon, deletes this project's profile directory, and opens a
fresh window. Everything the profile was signed into is gone; sign in again
in the window it opens.

Exit codes: 0 window closed normally; 1 the window could not be opened;
2 prerequisite failure (browser runtime missing, bad usage)."""
_BROWSER_AUTHORIZE_HELP_DEEP = _BROWSER_AUTHORIZE_HELP_DEEP.format(
    lifetime=SIGN_IN_COOKIE_LIFETIME_DAYS,
)


def browser_authorize(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke browser authorize",
        description=(
            f"{BROWSER_AUTHORIZE_USAGE}\n\n{_BROWSER_AUTHORIZE_HELP_DEEP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project", default=None,
        help="Project whose profile to sign in (default: this checkout's).",
    )
    parser.add_argument(
        "--url", default=None,
        help="Optional starting URL to open in the window.",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help=(
            "Delete this project's profile before opening the window, so the "
            "sign-in starts from an empty browser."
        ),
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, BROWSER_AUTHORIZE_USAGE)
    if parsed is None:
        return 2

    try:
        from yoke_harness import browser_client, browser_runtime_home
    except ImportError as exc:
        print(
            "yoke browser authorize requires yoke-harness in the "
            f"product install: {exc}",
            file=sys.stderr,
        )
        return 2

    from yoke_cli.config import browser_profile
    from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError

    try:
        project_key = browser_profile.profile_project_key(parsed.project)
    except ProjectSlugLookupError as exc:
        return _fail(parsed.json_mode, str(exc), code=2)
    runtime_dir = browser_runtime_home.ensure_materialized()
    authorize_js = runtime_dir / "src" / "authorize.js"
    if not authorize_js.is_file():
        return _fail(
            parsed.json_mode,
            f"the browser runtime is incomplete: {authorize_js} is missing. "
            "Run `yoke qa browser setup` to materialize it, then retry.",
            code=2,
        )

    _stop_daemon_holding_profile(browser_client)

    removed = (
        browser_profile.remove_profile_dir(parsed.project) if parsed.reset else None
    )
    if parsed.reset and not parsed.json_mode:
        print(
            f"Removed the previous {project_key} browser profile at "
            f"{browser_profile.profile_dir_display(removed)}."
            if removed is not None
            else f"No {project_key} browser profile to remove; starting fresh."
        )
    profile = browser_profile.ensure_profile_dir(parsed.project)

    command = ["node", str(authorize_js), "--profile-dir", str(profile)]
    if parsed.url:
        command.extend(["--url", parsed.url])
    if not parsed.json_mode:
        print(
            f"Opening the {project_key} browser profile at "
            f"{browser_profile.profile_dir_display(profile)}."
        )
    # The window itself tells the operator to sign in, once the window exists;
    # saying it here too printed the same instruction twice. In --json mode
    # that narration would corrupt the payload, so the child's stdout is
    # discarded rather than inherited.
    result = subprocess.run(
        command,
        cwd=str(runtime_dir),
        check=False,
        stdout=subprocess.DEVNULL if parsed.json_mode else None,
    )
    if result.returncode != 0:
        return _fail(
            parsed.json_mode,
            "the sign-in window exited with status "
            f"{result.returncode}. Run `yoke qa browser status` to check the "
            "browser runtime, then retry.",
            code=1,
        )

    try:
        kept = keep_sign_in_cookies(profile)
    except SignInCookieError as exc:
        return _fail(parsed.json_mode, str(exc), code=1)

    payload = {
        "ok": True,
        "project": project_key,
        "profile_dir": str(profile),
        "reset": bool(parsed.reset),
        "kept_sign_in_cookies": kept,
    }
    if parsed.json_mode:
        print(json.dumps(payload))
    else:
        print(
            f"Profile saved for project {project_key}. Kept {kept} session "
            f"cookie(s) for {SIGN_IN_COOKIE_LIFETIME_DAYS} days so the daemon "
            "opens this profile signed in."
        )
    return 0


def _stop_daemon_holding_profile(browser_client) -> None:
    """Release the profile lock a running daemon would otherwise hold.

    Chromium takes an exclusive lock on a profile directory, so a live daemon
    on this profile would make the sign-in window fail to open. The daemon is
    a machine singleton and every case run starts it on demand, so stopping it
    costs nothing.
    """
    state = browser_client.DaemonState.load()
    if state is None or not browser_client.daemon_running(state):
        return
    try:
        browser_client.daemon_stop()
    except RuntimeError:
        # Already gone between the check and the stop.
        pass


def _fail(json_mode: bool, message: str, *, code: int) -> int:
    if json_mode:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(f"yoke browser authorize: {message}", file=sys.stderr)
    return code


TOOL_SHAPED_SUBCOMMANDS = {
    ("browser", "authorize"): browser_authorize,
}

TOOL_SHAPED_USAGE = {
    "yoke browser authorize": (
        "Sign a project's persistent browser profile in once, in a plain "
        "window of the daemon's own Chromium."
    ),
}


__all__ = [
    "BROWSER_AUTHORIZE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "browser_authorize",
]
