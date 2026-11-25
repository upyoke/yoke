"""Shared steps for ``yoke browser authorize`` and ``yoke browser verify``.

Both resolve one project identity, prepare the machine's browser runtime, and
check the declared sites on that identity's own profile.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

from yoke_contracts.browser_identity import (
    BrowserIdentity,
    BrowserIdentityError,
    select_declared_identity,
)
from yoke_cli import browser_node_toolchain
from yoke_cli.commands.json_input import JSON_INPUT_HELP, load_json_input

IDENTITY_FLAG_HELP = (
    "Identity whose profile to use (default: the project's default_identity "
    "setting, else `default`, the project's original single profile). Other "
    "names must be declared in the project's browser-control capability settings."
)
DECLARATIONS_FLAG_HELP = (
    "The project's browser-control settings document as JSON, for a host that "
    "cannot read them itself (a Test Machine not connected to the project's "
    "control plane). Read it where the project is reachable with `yoke "
    "projects capability-settings get --project P --cap-type browser-control "
    "--json` and supply result.settings_json. A project without that "
    f"capability has only `default` and needs no declarations. {JSON_INPUT_HELP}"
)


class BrowserRuntime(NamedTuple):
    runtime_dir: Path
    node: Path
    env: dict[str, str]


def resolve_identity_target(
    project: str | None, identity: str | None, declarations_json: str | None = None
) -> tuple[str, BrowserIdentity]:
    """Return the project key and its declared identity, or raise naming why.

    Declarations come from the project's control plane, or from the settings
    document a caller supplies for a host that cannot reach it. Raises
    ``ProjectSlugLookupError`` or ``BrowserIdentityError``; both carry their
    recovery step in the message.
    """
    from yoke_cli.config import browser_profile
    from yoke_cli.config.browser_identities import resolve_identity

    key = browser_profile.profile_project_key(project)
    if declarations_json is None:
        return key, resolve_identity(key, identity)
    try:
        settings = load_json_input(declarations_json, "--declarations-json")
    except json.JSONDecodeError as exc:
        raise BrowserIdentityError(
            f"browser_identity_declarations_unreadable: --declarations-json is "
            f"not JSON ({exc}). Pass result.settings_json from `yoke projects "
            "capability-settings get --cap-type browser-control --json` verbatim."
        ) from None
    except ValueError as exc:
        raise BrowserIdentityError(
            f"browser_identity_declarations_unreadable: {exc}"
        ) from None
    if not isinstance(settings, dict):
        raise BrowserIdentityError(
            "browser_identity_declarations_unreadable: --declarations-json must "
            "be the browser-control settings object."
        )
    return key, select_declared_identity(settings, identity)


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
    """Probe the live profile or use the headless check once it is free."""
    from yoke_cli.config import browser_profile
    from yoke_harness import browser_identity_check, browser_live_profile

    if not identity.sites:
        return []
    profile = browser_profile.authorized_profile_dir(key, identity=identity.name)
    endpoint = None
    if profile is not None:
        # A QA daemon normally owns a separate copy. Release a daemon on
        # this exact profile before deciding whether the visible browser owns it.
        browser_identity_check.stop_profile_daemon(client, profile)
        try:
            endpoint = browser_live_profile.live_profile_endpoint(profile)
        except browser_live_profile.LiveProfileError as exc:
            raise browser_identity_check.SignInCheckError(str(exc)) from None
    return browser_identity_check.check_identity(
        identity,
        profile,
        node=runtime.node,
        runtime_dir=runtime.runtime_dir,
        env=runtime.env,
        live_endpoint=endpoint,
    )


__all__ = [
    "DECLARATIONS_FLAG_HELP",
    "IDENTITY_FLAG_HELP",
    "BrowserRuntime",
    "check_sign_in",
    "prepare_browser_runtime",
    "resolve_identity_target",
]
