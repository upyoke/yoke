"""``yoke github credential-helper refresh`` — repair the local helper bundle.

Client-local command (no dispatcher function id), registered in
:mod:`yoke_cli.commands.installer_local`. Republishes the content-addressed
git credential-helper bundle under the running interpreter's site-packages
when a prior helper is already installed there, and does nothing otherwise —
see :func:`yoke_cli.config.github_git_credentials.refresh_installed_helper`.
Safe to call unconditionally after any reinstall; ``yoke update`` and
``yoke self-host upgrade`` both invoke it via the freshly installed binary
once their own reinstall completes.
"""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_cli.config import github_git_credentials

__all__ = [
    "GITHUB_CREDENTIAL_HELPER_REFRESH_USAGE",
    "github_credential_helper_refresh",
]

GITHUB_CREDENTIAL_HELPER_REFRESH_USAGE = (
    "yoke github credential-helper refresh [--json]"
)


def github_credential_helper_refresh(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke github credential-helper refresh")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parser.parse_args(args)
    try:
        refreshed = github_git_credentials.refresh_installed_helper()
    except (OSError, github_git_credentials.GitHubCredentialBundleError) as exc:
        if parsed.json_mode:
            print(json.dumps({"refreshed": False, "error": str(exc)}))
        else:
            print(f"credential helper refresh failed: {exc}")
        return 1
    if parsed.json_mode:
        print(json.dumps({"refreshed": refreshed}))
    else:
        print(
            "Refreshed the installed git credential helper bundle."
            if refreshed
            else "No prior git credential helper installed; nothing to refresh."
        )
    return 0
