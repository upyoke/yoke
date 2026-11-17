"""``yoke browser open``: show a URL in one identity's live browser profile.

A Test Machine keeps one login store: its identity profiles. Every person-
facing browser use on the machine (a desktop mission page, the installer's
approval link through ``BROWSER``) opens here, so it carries the identity's
sign-in and the operator never signs in a second time. The command needs no
control-plane connection: it only reads the machine-local profile.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error

BROWSER_OPEN_USAGE = (
    "yoke browser open --project PROJECT --identity NAME [--json] URL"
)
BROWSER_OPEN_HELP = """\
Open URL in a visible window of an authorized identity's browser profile.

The window is the same Chromium `yoke browser authorize` signs in, so the
page opens signed in. When that profile's browser is already running, the URL
opens as a new tab there. An identity that was never authorized, or a profile
whose browser cannot start, refuses by name with its recovery step.

Use it as the standard BROWSER opener, for example:

  BROWSER='yoke browser open --project acme --identity operator %s'
"""


def browser_open(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke browser open",
        usage=BROWSER_OPEN_USAGE,
        description=BROWSER_OPEN_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug.")
    parser.add_argument("--identity", required=True, help="Authorized identity name.")
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON output."
    )
    parser.add_argument("url", help="Page to open.")
    parsed = parse_or_usage_error(parser, args, BROWSER_OPEN_USAGE)
    if parsed is None:
        return 2
    try:
        result = open_identity_url(parsed.project, parsed.identity, parsed.url)
    except (RuntimeError, ValueError, OSError) as exc:
        if parsed.json_mode:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"yoke browser open: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps({"ok": True, **result}))
    else:
        print(
            f"Opened {parsed.url} in identity {parsed.identity}'s browser "
            f"({result['profile_dir']})."
        )
    return 0


def open_identity_url(project: str, identity: str, url: str) -> dict:
    """Open *url* in the identity's profile window; raise naming any refusal."""
    from yoke_contracts.browser_identity import validate_identity_name
    from yoke_cli.commands.browser_sign_in import prepare_browser_runtime
    from yoke_cli.config import browser_profile

    name = validate_identity_name(identity)
    profile = browser_profile.authorized_profile_dir(project, identity=name)
    if profile is None:
        raise RuntimeError(
            f"browser_identity_not_authorized: identity {name} of project "
            f"{project} has no saved sign-in on this machine. From the operator "
            f"workstation run `yoke browser authorize --project {project} "
            f"--identity {name} --test-machine TEST_MACHINE`, then retry."
        )
    runtime = prepare_browser_runtime("open.js")
    # One Chromium holds a profile: a QA daemon on this profile gives it up
    # (and copies its sign-in again on its next check), so the visible window
    # is never a headless daemon page.
    from yoke_harness import browser_client, browser_identity_check

    browser_identity_check.stop_profile_daemon(browser_client, profile)
    completed = subprocess.run(
        [
            str(runtime.node),
            str(runtime.runtime_dir / "src" / "open.js"),
            "--profile-dir",
            str(profile),
            "--url",
            url,
        ],
        cwd=str(runtime.runtime_dir),
        env=runtime.env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    try:
        receipt = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError(
            f"browser_open_failed: the launcher exited {completed.returncode} "
            f"without a receipt. {(completed.stderr or '').strip()} Run `yoke qa "
            "browser status`, then retry."
        ) from None
    if not receipt.get("ok"):
        raise RuntimeError(str(receipt.get("error")))
    receipt.pop("ok", None)
    return {**receipt, "profile_dir": str(profile)}


TOOL_SHAPED_SUBCOMMANDS = {("browser", "open"): browser_open}
TOOL_SHAPED_USAGE = {
    "yoke browser open": (
        "Open a URL in a visible window of an authorized identity's browser profile."
    )
}

__all__ = [
    "BROWSER_OPEN_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "browser_open",
    "open_identity_url",
]
