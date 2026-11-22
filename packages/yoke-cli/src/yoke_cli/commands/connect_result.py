"""Complete a saved connection with its own convergent machine relay."""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any

from yoke_cli.config import (
    credential_repair,
    machine_registration,
    onboard_session_relay,
    writer,
)
from yoke_cli.config.onboard_apply_report_metadata import sanitize_text
from yoke_contracts.refusal_recovery import compose_refusal


def finish_connection(
    report: dict[str, Any], *, json_mode: bool, register: bool = False
) -> int:
    """Bind bootstrap credentials before converging the saved relay."""
    environment = str(report["env"])
    config_path = report.get("config")
    report.update(credential_shared_with=[], credential_unverified=[])
    if register:
        registration = machine_registration.register_this_machine(
            config_path, environment=environment
        )
        if not registration["registered"]:
            return _report_failure(
                report,
                compose_refusal(
                    "connection_machine_registration_failed: connection saved; machine registration failed",
                    evaluated=sanitize_text(str(registration["reason"])),
                    recovery="resolve the registration error and rerun the same `yoke connect` command",
                ),
                json_mode=json_mode,
            )
    try:
        report.update(
            credential_repair.repair_revoked_connections(
                environment, api_url=str(report["api_url"]), path=config_path
            )
        )
    except writer.MachineConfigWriteError as exc:
        return _report_failure(
            report,
            compose_refusal(
                "connection_credential_share_failed: connection saved; other "
                "connections to this server still hold a revoked credential",
                evaluated=sanitize_text(str(exc)),
                recovery="resolve the config error and rerun the same `yoke connect` command",
            ),
            json_mode=json_mode,
        )
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
        return _report_failure(
            report,
            compose_refusal(
                "connection_relay_setup_failed: connection saved; relay setup failed",
                evaluated=sanitize_text(str(exc)),
                recovery=f"retry the saved connection's relay with `{retry}`",
            ),
            json_mode=json_mode,
        )
    return _emit_result(report, json_mode=json_mode)


def _report_failure(
    report: dict[str, Any], message: str, *, json_mode: bool
) -> int:
    report.update(ok=False, connection_saved=True)
    report["session_relay"] = {"installed": False, "error": message}
    return _emit_result(report, json_mode=json_mode)


def _emit_result(report: dict[str, Any], *, json_mode: bool) -> int:
    relay = report["session_relay"]
    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_summary(report)
        if "error" in relay:
            print(relay["error"], file=sys.stderr)
        elif relay["installed"]:
            action = "reused" if relay["reused"] else "installed"
            print(f"machine relay {action} for connection {report['env']}")
    return int("error" in relay)


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
    if report.get("credential_shared_with"):
        names = ", ".join(report["credential_shared_with"])
        print(f"also moved to the new credential: {names}")
    for name in report.get("credential_unverified") or ():
        print(
            f"warning: could not check connection {name}'s token; "
            f"verify it with `yoke --env {name} status`",
            file=sys.stderr,
        )
