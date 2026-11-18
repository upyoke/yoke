"""Complete a saved connection with its own convergent machine relay."""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any

from yoke_cli.config import onboard_session_relay
from yoke_cli.config.onboard_apply_report_metadata import sanitize_text
from yoke_contracts.refusal_recovery import compose_refusal


def finish_connection(report: dict[str, Any], *, json_mode: bool) -> int:
    """Keep saved credentials when relay setup fails, and report partial success."""
    environment = str(report["env"])
    config_path = report.get("config")
    code = 0
    try:
        outcome = onboard_session_relay.install(
            local_destination=False,
            environment=environment,
            config_path=config_path,
            # Installation is the outcome here, not authenticated readiness.
            # The ambient doctor's wait could observe another active connection
            # when --no-activate saved this one beside it.
            wait_for_connection=lambda _timeout: False,
        )
        report["session_relay"] = {
            "installed": outcome.installed,
            "reused": outcome.reused,
        }
    except onboard_session_relay.OnboardSessionRelayError as exc:
        retry = shlex.join(
            onboard_session_relay.relay_command(
                "install", config_path=config_path, environment=environment
            )
        )
        message = compose_refusal(
            "connection_relay_setup_failed: connection saved; relay setup failed",
            evaluated=sanitize_text(str(exc)),
            recovery=f"retry the saved connection's relay with `{retry}`",
        )
        report.update(ok=False, connection_saved=True)
        report["session_relay"] = {"installed": False, "error": message}
        code = 1
    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_summary(report)
        relay = report["session_relay"]
        if code:
            print(relay["error"], file=sys.stderr)
        elif relay["installed"]:
            print(f"machine relay installed for connection {environment}")
    return code


def _print_summary(report: dict[str, Any]) -> None:
    print(f"connected: {report.get('api_url')} (env {report.get('env')})")
    identity = report.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    actor = identity.get("actor")
    actor = actor if isinstance(actor, dict) else {}
    if actor.get("label") or actor.get("id") is not None:
        print(f"actor: {actor.get('label')} (id={actor.get('id')})")
    health = report.get("health")
    health = health if isinstance(health, dict) else {}
    if health.get("build"):
        print(f"server build: {health.get('build')}")
    if report.get("activated"):
        print(f"active env: {report.get('env')}")
    else:
        print(
            "connection written without activation; switch later with "
            f"`yoke env use {report.get('env')}`"
        )
    print(f"verify anytime with `yoke --env {report.get('env')} status`")
