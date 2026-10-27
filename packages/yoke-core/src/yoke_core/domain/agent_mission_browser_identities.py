"""The browser identities an exploratory mission needs, as walker instructions.

A mission names its identities in ``method_config.browser_identities`` or uses
the project declarations covering its target origin. The walker proves each
one signed in, site by site, on the Test Machine after setup and before browsing.
The walker reauthorizes expired sites; only prohibited password or credential
entry is a human gate naming the identity, site, account and resume state.
"""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import urlsplit

from yoke_contracts.browser_identity import parse_identity_declarations
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.qa_plan_execution_store import marker


def mission_browser_settings(conn: Any, bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Read declarations once, only when a mission needs project defaults."""
    target = bundle.get("execution_target") or {}
    project_id = (target.get("project") or {}).get("id")
    if (
        conn is None
        or not project_id
        or not any(
            case.get("capture_runner") == "agent_mission"
            and not (case.get("method_config") or {}).get("browser_identities")
            for case in bundle["cases"]
        )
    ):
        return {}
    raw = query_scalar(
        conn,
        f"SELECT settings FROM project_capabilities WHERE project_id={marker(conn)} "
        f"AND type={marker(conn)}",
        (int(project_id), "browser-control"),
    )
    if raw is None:
        return {}
    try:
        settings = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(settings, Mapping):
            raise ValueError("settings must be an object")
    except ValueError as exc:
        raise ValueError(
            "browser_identity_declaration_invalid: browser-control settings must "
            "be a JSON object. Repair them with yoke projects capability-settings "
            "set --project P --cap-type browser-control."
        ) from exc
    return dict(settings)


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower()


def _target_identities(
    settings: Mapping[str, Any], target: Mapping[str, Any]
) -> list[str]:
    base_url = (target.get("endpoints") or {}).get("base_url")
    if not base_url:
        return []
    origin = _origin(str(base_url))
    return [
        name
        for name, identity in parse_identity_declarations(settings).items()
        if any(_origin(site.origin) == origin for site in identity.sites)
    ]


def walker_identity_dispatch(
    case: Mapping[str, Any],
    host_command_base: str | None,
    *,
    browser_settings: Mapping[str, Any],
    execution_target: Mapping[str, Any],
) -> tuple[list[str], list[str], str]:
    """Return the identities, their exact verify commands, and the prompt clause."""
    identities = list((case.get("method_config") or {}).get("browser_identities") or [])
    if not identities:
        identities = _target_identities(browser_settings, execution_target)
    prefix = f"{host_command_base} -- " if host_command_base else ""
    commands = [
        f"{prefix}yoke browser verify --project PROJECT "
        f"--identity {name} --declarations-json DECLARATIONS_JSON --json"
        for name in identities
    ]
    if not identities:
        return identities, commands, ""
    clause = (
        f"Available browser identities for this mission: {', '.join(identities)}. "
        "Use the identity whose account fits the case. "
        + (
            "The Test Machine cannot read the project's declarations, so read them "
            "here first with "
            if host_command_base
            else "Read the controller project declarations with "
        )
        + "`yoke projects capability-settings get --project "
        "PROJECT --cap-type browser-control --json` and pass its "
        "result.settings_json verbatim as DECLARATIONS_JSON. After setup "
        "succeeds and before browsing, check each identity with "
        + "; ".join(f"`{command}`" for command in commands)
        + ", and pass `--identity NAME` to every step acting as that identity. "
        "For an expired site, run `yoke browser authorize --project PROJECT "
        "--identity NAME --declarations-json DECLARATIONS_JSON` on this host, "
        "which opens a window only for the expired sites. Re-sign in yourself "
        "or route an approval to steering. Return WALK_STATUS: HUMAN_GATE only "
        "when re-signing in needs a password or credential the agent may not "
        "type, naming that one entry, the identity, the site and the account "
        "from the report, and resume state. Sign-ins live in the host's "
        "identity store; never save or restore browser profiles. "
    )
    return identities, commands, clause


__all__ = ["mission_browser_settings", "walker_identity_dispatch"]
