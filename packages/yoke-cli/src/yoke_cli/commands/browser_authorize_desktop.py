"""Authorize the installer's native desktop browser without changing QA identities."""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

from yoke_cli.commands.browser_sign_in import (
    prepare_browser_runtime,
    resolve_identity_target,
)


def authorize_with_desktop(parsed, args) -> int:
    """One GUI command owns both checks and produces one combined receipt."""
    from yoke_cli.commands.browser_authorize import browser_authorize

    original_args = [arg for arg in args if arg != "--include-desktop-browser"]
    if not parsed.json_mode:
        result = browser_authorize(original_args)
        return result or authorize_desktop(
            SimpleNamespace(**{**vars(parsed), "reset": False})
        )
    original, native = StringIO(), StringIO()
    with redirect_stdout(original):
        result = browser_authorize(original_args)
    payload = json.loads(original.getvalue())
    if result == 0:
        with redirect_stdout(native):
            result = authorize_desktop(
                SimpleNamespace(**{**vars(parsed), "reset": False})
            )
        payload["desktop_browser"] = json.loads(native.getvalue())
        payload["ok"] = result == 0
    print(json.dumps(payload))
    return result


def authorize_desktop(parsed) -> int:
    from yoke_cli.commands.browser_authorize import _fail
    from yoke_harness import browser_identity_check as checks
    from yoke_harness import desktop_browser_sign_in as desktop
    from yoke_harness import browser_client
    from yoke_harness.browser_human_gate import human_gate

    try:
        if parsed.reset:
            raise RuntimeError(
                "desktop_browser_reset_refused: desktop sign-ins are kept live; omit --reset. Only automation identity profiles may be reset."
            )
        project, identity = resolve_identity_target(
            parsed.project, parsed.identity, parsed.declarations_json
        )
        runtime = prepare_browser_runtime("verify-sign-in.js")
        kind = desktop.browser_kind()
        sites = desktop.check_desktop(identity, runtime, kind=kind)

        def say(line):
            print(line, file=sys.stderr if parsed.json_mode else sys.stdout, flush=True)

        say(checks.summarize(kind, sites))
        if checks.sites_in(sites, checks.UNREACHABLE):
            raise RuntimeError(
                "desktop_browser_site_unreachable: repair the declared site's probe or network connection, then retry; no sign-in window was opened."
            )
        expired = checks.sites_in(sites, checks.EXPIRED)
        if expired:
            for line in checks.sign_in_request(kind, expired):
                say(line)
            say(
                "Close all desktop browser windows after signing in; Yoke then checks again."
            )
            with human_gate(
                browser_client,
                runtime.runtime_dir,
                project=project,
                identity="desktop-" + kind.lower(),
            ):
                desktop.sign_in_window(kind, [site["origin"] for site in expired])
            sites = desktop.check_desktop(identity, runtime, kind=kind)
            say(checks.summarize(kind, sites))
        incomplete = [
            site["site"] for site in sites if site["state"] != checks.SIGNED_IN
        ]
        if incomplete:
            raise RuntimeError(
                "desktop_browser_sign_in_incomplete: "
                + ", ".join(incomplete)
                + "; rerun browser authorize and sign in with the named account."
            )
        payload = {
            "ok": True,
            "project": project,
            "identity": identity.name,
            "browser": kind,
            "sites": sites,
            "window_opened": bool(expired),
            "kept_live_through_reset": True,
        }
        if parsed.json_mode:
            print(json.dumps(payload))
        else:
            say(
                f"{kind} desktop sign-in verified; kept live through reset and excluded from golden capture."
            )
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        return _fail(parsed.json_mode, str(exc), code=1)
