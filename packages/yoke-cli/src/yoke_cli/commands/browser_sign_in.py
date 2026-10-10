"""Shared steps for ``yoke browser authorize`` and ``yoke browser verify``.

Both resolve one project identity, prepare the machine's browser runtime, and
check that identity's declared sites headless on its own profile.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, NamedTuple

from yoke_contracts.browser_identity import BrowserIdentity
from yoke_cli import browser_node_toolchain

IDENTITY_FLAG_HELP = (
    "Identity whose profile to use (default: `default`, the project's original "
    "single profile). Other names must be declared in the project's "
    "browser-control capability settings."
)


class BrowserRuntime(NamedTuple):
    runtime_dir: Path
    node: Path
    env: dict[str, str]


def resolve_identity_target(
    project: str | None, identity: str | None
) -> tuple[str, BrowserIdentity]:
    """Return the project key and its declared identity, or raise naming why.

    Raises ``ProjectSlugLookupError`` or ``BrowserIdentityError``; both carry
    their recovery step in the message.
    """
    from yoke_cli.config import browser_profile
    from yoke_cli.config.browser_identities import resolve_identity

    key = browser_profile.profile_project_key(project)
    return key, resolve_identity(key, identity)


def prepare_browser_runtime(script: str) -> BrowserRuntime:
    """Materialize the runtime and its prerequisites; raise ``RuntimeError``."""
    from yoke_harness import browser_runtime_home, browser_setup

    runtime_dir = browser_runtime_home.ensure_materialized()
    if not (runtime_dir / "src" / script).is_file():
        raise RuntimeError(
            f"the browser runtime is incomplete: {runtime_dir / 'src' / script} is "
            "missing. Run `yoke qa browser setup` to materialize it, then retry."
        )
    toolchain = browser_node_toolchain.ensure_node_toolchain()
    env = browser_setup.ensure_browser_runtime(
        runtime_dir, toolchain, emit=lambda message: print(message, file=sys.stderr)
    )
    return BrowserRuntime(runtime_dir, Path(toolchain.node), env)


def check_sign_in(
    client, runtime: BrowserRuntime, key: str, identity: BrowserIdentity
) -> list[dict[str, Any]]:
    """Check each declared site; the identity's own daemon is stopped first."""
    from yoke_cli.config import browser_profile
    from yoke_harness import browser_identity_check

    if not identity.sites:
        return []
    profile = browser_profile.authorized_profile_dir(key, identity=identity.name)
    if profile is not None:
        browser_identity_check.stop_profile_daemon(client, profile)
    return browser_identity_check.check_identity(
        identity,
        profile,
        node=runtime.node,
        runtime_dir=runtime.runtime_dir,
        env=runtime.env,
    )


__all__ = [
    "IDENTITY_FLAG_HELP",
    "BrowserRuntime",
    "check_sign_in",
    "prepare_browser_runtime",
    "resolve_identity_target",
]
