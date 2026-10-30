"""Stop and restore only the selected local source's installed relay."""

from __future__ import annotations

import os
import subprocess
import sys

from yoke_cli.config.session_relay_instance import (
    resolve_relay_instance,
    RELAY_STATE_DIR_ENV,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.tools import session_relay_plist, session_relay_systemd
from yoke_core.tools.launchctl_boundary import (
    bootstrap_launchd_job,
    launchd_target,
    run_launchctl,
    wait_for_launchd_unload,
)


class SourceServiceError(RuntimeError):
    """The source service requires an explicit recovery."""


def plan(dsn: str) -> dict:
    from yoke_core.domain import db_backend, yoke_connected_env, universe_source_pause

    env = yoke_connected_env.load_active()
    if env is None or env.backend != "postgres":
        return {}
    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV, dsn_file_env=db_backend.PG_DSN_FILE_ENV
    )
    if universe_source_pause._marker(dsn) != universe_source_pause._marker(
        resolved.dsn
    ):
        return {}
    instance = resolve_relay_instance(environment=env.environment)
    relay = status(instance)
    if not relay.supported or not relay.loaded:
        return {}
    if os.environ.get(RELAY_STATE_DIR_ENV) == str(instance.state_dir):
        raise SourceServiceError(
            compose_refusal(
                "universe_export_relay_owned: this exporter runs under the source relay it must stop",
                recovery="run `yoke universe export --pause-source` from a standalone terminal",
            )
        )
    return {"relay_environment": instance.environment}


def status(instance):
    if sys.platform == "linux":
        return session_relay_systemd.relay_systemd_status(instance=instance)
    return session_relay_plist.relay_launchd_status(instance=instance)


def stop(record: dict) -> None:
    if not record:
        return
    instance = resolve_relay_instance(environment=record["relay_environment"])
    if sys.platform == "linux":
        unit = session_relay_systemd.relay_unit_path(instance)
        session_relay_systemd._checked(
            ["systemctl", "--user", "stop", unit.name], subprocess.run
        )
    else:
        target = launchd_target(instance.label)
        run_launchctl(["launchctl", "bootout", target])
        if not wait_for_launchd_unload(target, run=run_launchctl):
            raise RuntimeError("source relay did not stop")
    if status(instance).loaded:
        raise RuntimeError("source relay still running")


def start(record: dict) -> None:
    if not record:
        return
    instance = resolve_relay_instance(environment=record["relay_environment"])
    if status(instance).loaded:
        return
    if sys.platform == "linux":
        unit = session_relay_systemd.relay_unit_path(instance)
        session_relay_systemd._checked(
            ["systemctl", "--user", "start", unit.name], subprocess.run
        )
    else:
        paths = session_relay_plist.relay_launchd_paths(instance=instance)
        target = launchd_target(instance.label)
        result = bootstrap_launchd_job(
            target.rsplit("/", 1)[0], paths.plist, run=run_launchctl
        )
        if result.returncode:
            raise RuntimeError("source relay could not start")
    if not status(instance).loaded:
        raise RuntimeError("source relay did not resume")
