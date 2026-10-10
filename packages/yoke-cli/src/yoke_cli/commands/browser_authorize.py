"""``yoke browser authorize`` — the operator signs one browser identity in.

An agent must never complete a sign-in, so the signed-in state a Browser case
or an exploratory walker needs comes from the operator. This opens one project
identity's persistent browser profile in a plain window of the browser
daemon's own Chromium — a directly spawned process, not an automation-
controlled one — so identity providers that refuse automated browsers still
let the operator sign in. It first checks each site the identity declares and
asks for a human only when a session has really expired.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import List

from yoke_contracts.browser_identity import BrowserIdentityError
from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.browser_sign_in import (
    DECLARATIONS_FLAG_HELP,
    IDENTITY_FLAG_HELP,
    check_sign_in,
    prepare_browser_runtime,
    resolve_identity_target,
)
from yoke_cli.config.browser_profile_cookies import (
    SIGN_IN_COOKIE_LIFETIME_DAYS,
    SignInCookieError,
    keep_sign_in_cookies,
)


BROWSER_AUTHORIZE_USAGE = (
    "yoke browser authorize [--project PROJECT] [--identity NAME] [--url URL] "
    "[--declarations-json JSON] [--reset] [--json]"
)

_BROWSER_AUTHORIZE_HELP_DEEP = """\
Sign one identity of a project in, but only where it has to be. An identity is
one persona's whole browser profile -- every site that persona uses, for
example a Google account, the product account and a payment provider
together. A project declares identities under names it chooses, each listing
its sites and a signed-in check per site, in its browser-control capability
settings; `default` always exists and is the project's original profile.

The command first checks every declared site headless on the identity's
profile and reports each one (`buyer: google ok, yoke ok, paypal expired`).
When all are signed in it returns at once and opens nothing. Otherwise it
opens a window with one tab per expired site, naming the identity, the site
and the account to use, then checks again after the window closes and fails
naming any site still signed out. A site whose check cannot be reached fails
without a window: a sign-in cannot fix it. An identity that declares no sites
has nothing to check, so the window opens as it always did.

While the window is open no automated browser runs on this machine: every
browser daemon (any project, any profile) is stopped first, and starting one
is refused with `browser_human_gate_active` until the window closes. Cases and
walkers start their daemon again on their next command.

The window is a directly spawned browser process, never an automated one.
Google's sign-in refuses an automation-controlled browser ("Couldn't sign you
in. This browser or app may not be secure"). It is the daemon's own Chromium,
launched with the daemon's own cookie-encryption switches, because Chromium
drops any stored cookie it cannot decrypt when it opens a profile.

Close every authorization window to finish. On macOS, where Chromium may stay
running without a window, Yoke asks it to shut down after the last window
closes. If no macOS window opens in 30 seconds, or the browser runs for 30
minutes, the command stops it and names the condition; if it still holds the
profile 10 seconds later, quit the named PID and rerun without --reset.

Worked examples:

  yoke browser authorize                          # default identity, this checkout
  yoke browser authorize --project yoke --identity admin
  yoke browser verify --project yoke --identity admin   # check without a window

Each identity's profile is kept with the project's machine-local capability
secrets at owner-only permissions, keyed by project slug and identity name. On
a Test Machine that keeps live identities (~/.yoke-browser-identities), the
profile is that live store entry, so a full reset keeps the sign-in.

Session cookies (no expiry) are given an explicit {lifetime}-day expiry when the
window closes, so the sign-in survives Chromium reopening the profile.

  yoke browser authorize --identity admin --reset

deletes that identity's profile and opens a fresh window for every declared
site; other identities are untouched.

Exit codes: 0 signed in (window opened or not needed); 1 the window could not
be opened, a site could not be checked, or a site is still signed out;
2 prerequisite failure (browser runtime missing, undeclared identity, bad
usage)."""
_BROWSER_AUTHORIZE_HELP_DEEP = _BROWSER_AUTHORIZE_HELP_DEEP.format(
    lifetime=SIGN_IN_COOKIE_LIFETIME_DAYS,
)


def browser_authorize(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke browser authorize",
        description=(f"{BROWSER_AUTHORIZE_USAGE}\n\n{_BROWSER_AUTHORIZE_HELP_DEEP}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project whose profile to sign in (default: this checkout's).",
    )
    parser.add_argument("--identity", default=None, help=IDENTITY_FLAG_HELP)
    parser.add_argument(
        "--declarations-json", default=None, help=DECLARATIONS_FLAG_HELP
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Starting URL to open instead of the expired sites' origins.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Delete this identity's profile before opening the window, so the "
            "sign-in starts from an empty browser."
        ),
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, BROWSER_AUTHORIZE_USAGE)
    if parsed is None:
        return 2

    try:
        from yoke_harness import browser_client, browser_identity_check
        from yoke_harness.browser_human_gate import human_gate
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
        project_key, identity = resolve_identity_target(
            parsed.project, parsed.identity, parsed.declarations_json
        )
        runtime = prepare_browser_runtime("authorize.js")
    except (ProjectSlugLookupError, BrowserIdentityError, RuntimeError) as exc:
        return _fail(parsed.json_mode, str(exc), code=2)
    label = f"project {project_key} identity {identity.name}"
    say = (lambda line: None) if parsed.json_mode else print

    expired = list(identity.sites)
    if identity.sites and not parsed.reset:
        try:
            sites = check_sign_in(browser_client, runtime, project_key, identity)
        except browser_identity_check.SignInCheckError as exc:
            return _fail(parsed.json_mode, str(exc), code=1)
        say(browser_identity_check.summarize(identity.name, sites))
        unreachable = browser_identity_check.sites_in(
            sites, browser_identity_check.UNREACHABLE
        )
        if unreachable:
            return _fail(
                parsed.json_mode,
                f"browser_sign_in_site_unreachable: {label} could not check "
                + ", ".join(f"{s['site']} ({s['detail']})" for s in unreachable)
                + ". A sign-in cannot fix a site the check cannot reach; repair "
                "the site or its declared probe, then retry.",
                code=1,
            )
        expired = [
            check
            for check in identity.sites
            if check.site
            in {
                s["site"]
                for s in browser_identity_check.sites_in(
                    sites, browser_identity_check.EXPIRED
                )
            }
        ]
        if not expired:
            return _done(parsed.json_mode, project_key, identity.name, sites, None)

    try:
        with human_gate(
            browser_client,
            runtime.runtime_dir,
            project=project_key,
            identity=identity.name,
        ) as stopped:
            if stopped:
                say(f"Stopped {len(stopped)} automated browser daemon(s) first.")
            removed = (
                browser_profile.remove_profile_dir(project_key, identity=identity.name)
                if parsed.reset
                else None
            )
            if parsed.reset:
                say(
                    f"Removed the previous {label} browser profile at "
                    f"{browser_profile.profile_dir_display(removed)}."
                    if removed is not None
                    else f"No {label} browser profile to remove; starting fresh."
                )
            profile = browser_profile.ensure_profile_dir(
                project_key, identity=identity.name
            )
            urls = [parsed.url] if parsed.url else [check.origin for check in expired]
            for line in browser_identity_check.sign_in_request(
                identity.name,
                [
                    {"site": c.site, "origin": c.origin, "account": c.account}
                    for c in expired
                ],
            ):
                say(line)
            say(
                f"Opening the {label} browser profile at "
                f"{browser_profile.profile_dir_display(profile)}."
            )
            kept = _sign_in_window(runtime, profile, urls, parsed.json_mode)
    except (RuntimeError, BrowserIdentityError) as exc:
        return _fail(parsed.json_mode, str(exc), code=1)

    sites = []
    if identity.sites:
        try:
            sites = check_sign_in(browser_client, runtime, project_key, identity)
        except browser_identity_check.SignInCheckError as exc:
            return _fail(parsed.json_mode, str(exc), code=1)
        say(browser_identity_check.summarize(identity.name, sites))
        still = [s for s in sites if s["state"] != browser_identity_check.SIGNED_IN]
        if still:
            return _fail(
                parsed.json_mode,
                f"browser_sign_in_incomplete: {label} is still not signed in to "
                + ", ".join(s["site"] for s in still)
                + ". Run `yoke browser authorize"
                f" --project {project_key} --identity {identity.name}` again and "
                "sign in to each named site before closing the window.",
                code=1,
            )
    return _done(
        parsed.json_mode, project_key, identity.name, sites, kept, profile, parsed.reset
    )


def _sign_in_window(runtime, profile, urls: list[str], json_mode: bool) -> int:
    """Run the plain window to completion; return the session cookies kept."""
    command = [
        str(runtime.node),
        str(runtime.runtime_dir / "src" / "authorize.js"),
        "--profile-dir",
        str(profile),
    ]
    for url in urls:
        command.extend(["--url", url])
    # The window itself tells the operator to sign in, once the window exists.
    # In --json mode that narration would corrupt the payload, so the child's
    # stdout is discarded rather than inherited.
    result = subprocess.run(
        command,
        cwd=str(runtime.runtime_dir),
        check=False,
        env=runtime.env,
        stdout=subprocess.DEVNULL if json_mode else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"the sign-in window exited with status {result.returncode}. "
            + (
                (result.stderr or "").strip()
                or "Run `yoke qa browser status` to check the browser runtime, "
                "then retry."
            )
        )
    try:
        return keep_sign_in_cookies(profile)
    except SignInCookieError as exc:
        raise RuntimeError(str(exc)) from None


def _done(json_mode, project_key, identity, sites, kept, profile=None, reset=False):
    payload = {
        "ok": True,
        "project": project_key,
        "identity": identity,
        "window_opened": kept is not None,
        "reset": bool(reset),
        "sites": sites,
    }
    if kept is not None:
        payload.update(profile_dir=str(profile), kept_sign_in_cookies=kept)
    if json_mode:
        print(json.dumps(payload))
    elif kept is None:
        print(
            f"Every declared site is signed in for identity {identity}; no window opened."
        )
    else:
        print(
            f"Profile saved for project {project_key} identity {identity}. Kept "
            f"{kept} session cookie(s) for {SIGN_IN_COOKIE_LIFETIME_DAYS} days so "
            "the daemon opens this profile signed in."
        )
    return 0


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
        "Sign one project browser identity in where its declared sites have "
        "expired, in a plain window of the daemon's own Chromium."
    ),
}


__all__ = [
    "BROWSER_AUTHORIZE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "browser_authorize",
]
