"""Shared explanation of the active universe's machine-local reachability."""

from yoke_cli.config import machine_config
from yoke_contracts.machine_config.schema_transport import POSTGRES_TRANSPORTS

LOCAL_REACHABILITY_NOTICE = (
    "Reachable here only. This universe runs on this computer. Other people "
    "and computers can't connect to it. To work with a team or a second "
    "machine, set up a team server: `yoke self-host init`."
)


def active_connection_is_local(config_path=None) -> bool:
    try:
        connection = machine_config.active_connection(config_path)
    except (OSError, RuntimeError, ValueError):
        return False
    return connection.get("transport") in POSTGRES_TRANSPORTS
