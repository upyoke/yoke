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


BROWSER_AUTHORIZE_USAGE = (
    "yoke browser authorize [--project PROJECT] [--url URL] [--json]"
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
other installed browser because the profile's cookies are encrypted against
that binary's OS keychain entry; a profile signed in with a different browser
is unreadable to the daemon afterwards.

Worked examples:

  yoke browser authorize                      # the project of this checkout
  yoke browser authorize --project yoke
  yoke browser authorize --url https://app.upyoke.com

The browser daemon is a machine singleton and Chromium locks a profile
directory, so a running daemon is stopped first; the next case run starts it
again on the profile you just signed into.

Sessions expire, and that needs no machinery: an expired session lands a
walker on a sign-in page, which is already the human gate it raises. Run this
again for that site.

Exit codes: 0 window closed normally; 1 the window could not be opened;
2 prerequisite failure (browser runtime missing, bad usage)."""


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

    profile = browser_profile.ensure_profile_dir(parsed.project)
    project_key = browser_profile.profile_project_key(parsed.project)
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

    command = ["node", str(authorize_js), "--profile-dir", str(profile)]
    if parsed.url:
        command.extend(["--url", parsed.url])
    if not parsed.json_mode:
        print(
            f"Opening the {project_key} browser profile at "
            f"{browser_profile.profile_dir_display(profile)}.\n"
            "Sign in to whatever sites you need, then close the window."
        )
    result = subprocess.run(command, cwd=str(runtime_dir), check=False)
    if result.returncode != 0:
        return _fail(
            parsed.json_mode,
            "the sign-in window exited with status "
            f"{result.returncode}. Run `yoke qa browser status` to check the "
            "browser runtime, then retry.",
            code=1,
        )

    payload = {
        "ok": True,
        "project": project_key,
        "profile_dir": str(profile),
    }
    if parsed.json_mode:
        print(json.dumps(payload))
    else:
        print(f"Profile saved for project {project_key}.")
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
