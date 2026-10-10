"""``yoke browser verify`` — is one browser identity still signed in?

Checks every site a project identity declares, headless on that identity's
own profile, and reports each site separately. It only reads: nothing is
typed, clicked or signed in, and no window opens. ``yoke browser authorize``
runs the same check first and asks a human only for the sites it reports
expired.
"""

from __future__ import annotations

import argparse
import json
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

BROWSER_VERIFY_USAGE = (
    "yoke browser verify [--project PROJECT] [--identity NAME] "
    "[--declarations-json JSON] [--json]"
)

_BROWSER_VERIFY_HELP_DEEP = """\
Check, site by site, whether one identity's browser profile is still signed
in. Each site the identity declares in the project's browser-control
capability settings carries its own check: a URL plus either a selector that
only a signed-in page shows, or the HTTP status a signed-in request answers.
The report names every site:

  buyer: google ok, yoke ok, paypal expired

`expired` means the site answered and is signed out; sign in with
`yoke browser authorize --identity NAME`, which opens a window only for the
expired sites. `unreachable` means the check got no answer, which no sign-in
fixes: repair the site or its declared probe. The identity's own browser
daemon is stopped for the check (Chromium locks a profile); the next case
starts it again.

Worked examples:

  yoke browser verify --project plat --identity admin
  yoke browser verify --identity member --json

Exit codes: 0 every declared site signed in (or none declared); 1 a site is
expired or unreachable, or the check could not run; 2 prerequisite failure
(browser runtime missing, undeclared identity, bad usage)."""


def browser_verify(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke browser verify",
        description=f"{BROWSER_VERIFY_USAGE}\n\n{_BROWSER_VERIFY_HELP_DEEP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--identity", default=None, help=IDENTITY_FLAG_HELP)
    parser.add_argument(
        "--declarations-json", default=None, help=DECLARATIONS_FLAG_HELP
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, BROWSER_VERIFY_USAGE)
    if parsed is None:
        return 2
    try:
        from yoke_harness import browser_client, browser_identity_check
    except ImportError as exc:
        print(
            f"yoke browser verify requires yoke-harness in the product install: {exc}",
            file=sys.stderr,
        )
        return 2
    from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError

    try:
        project_key, identity = resolve_identity_target(
            parsed.project, parsed.identity, parsed.declarations_json
        )
        runtime = (
            prepare_browser_runtime("verify-sign-in.js") if identity.sites else None
        )
    except (ProjectSlugLookupError, BrowserIdentityError, RuntimeError) as exc:
        return _report(parsed.json_mode, {"ok": False, "error": str(exc)}, 2)
    try:
        sites = (
            check_sign_in(browser_client, runtime, project_key, identity)
            if runtime is not None
            else []
        )
    except browser_identity_check.SignInCheckError as exc:
        return _report(parsed.json_mode, {"ok": False, "error": str(exc)}, 1)
    signed_in = all(site["state"] == browser_identity_check.SIGNED_IN for site in sites)
    payload = {
        "ok": signed_in,
        "project": project_key,
        "identity": identity.name,
        "summary": browser_identity_check.summarize(identity.name, sites),
        "sites": sites,
    }
    return _report(parsed.json_mode, payload, 0 if signed_in else 1)


def _report(json_mode: bool, payload: dict, code: int) -> int:
    if json_mode:
        print(json.dumps(payload))
    elif "error" in payload:
        print(f"yoke browser verify: {payload['error']}", file=sys.stderr)
    else:
        print(payload["summary"])
        for site in payload["sites"]:
            if site["state"] != "signed_in":
                print(f"  {site['site']}: {site['state']} — {site['detail']}")
    return code


TOOL_SHAPED_SUBCOMMANDS = {("browser", "verify"): browser_verify}

TOOL_SHAPED_USAGE = {
    "yoke browser verify": (
        "Check each site a project browser identity declares and report which "
        "are signed in, without opening a window."
    ),
}

__all__ = [
    "BROWSER_VERIFY_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "browser_verify",
]
