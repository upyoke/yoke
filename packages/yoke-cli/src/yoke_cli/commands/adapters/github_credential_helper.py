"""``yoke github credential-helper refresh`` — repair the local helper bundle.

Client-local command (no dispatcher function id), registered in
:mod:`yoke_cli.commands.installer_local`. Rebuilds the content-addressed git
credential-helper bundle whenever a registered checkout's git config still
names it, whether or not the underlying file currently exists — the exact
repair a packaged reinstall (``uv tool install --reinstall``) needs, since
that reinstall replaces the tool virtualenv's site-packages wholesale and
orphans any files a *previous* run wrote there at runtime, while the git
config that still names that path survives untouched. See
:func:`yoke_cli.config.github_repo_helper_reconnect.restore_missing_bundle`.
A no-op when no registered checkout references a Yoke helper, so it is safe
to call unconditionally after any reinstall. The public installer
(``packaging/public-installer/install.py``) invokes it via the freshly
installed binary as the last step of every successful run, whether run
directly (``curl | sh``) or by ``yoke update``'s own reinstall; a genuine
repair failure there fails that run the same way a product-boundary-audit
failure does. ``yoke update``'s already-current fast path, which skips
rerunning the installer entirely, calls
:func:`yoke_cli.config.github_repo_helper_reconnect.restore_missing_bundle`
directly instead.
"""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_cli.config import github_repo_helper_reconnect

__all__ = [
    "GITHUB_CREDENTIAL_HELPER_REFRESH_USAGE",
    "github_credential_helper_refresh",
]

GITHUB_CREDENTIAL_HELPER_REFRESH_USAGE = (
    "yoke github credential-helper refresh [--config PATH] [--json]"
)


def github_credential_helper_refresh(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke github credential-helper refresh")
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parser.parse_args(args)
    result = github_repo_helper_reconnect.restore_missing_bundle(parsed.config_path)
    error = result.get("error")
    if parsed.json_mode:
        print(json.dumps(result))
    elif result["configured"] is False:
        print(
            "No registered checkout references a git credential helper; nothing to refresh."
        )
    else:
        if result["repaired"]:
            print("Rebuilt the git credential helper bundle a reinstall had wiped.")
        if error:
            print(f"credential helper repair failed: {error}")
    return 1 if error else 0
