"""Purge superseded universe latches and per-machine latches without an owner."""

MINIMUM_SERVING_VERSION = "next-release"


def apply(conn):
    """Keep Run onboard and history for live and retired registered machines."""
    conn.execute(
        "DELETE FROM overview_activation_facts WHERE module_key <> 'run_onboard'"
    )
    conn.execute(
        "DELETE FROM overview_machine_activation_facts "
        "WHERE machine_id NOT IN (SELECT machine_id FROM machines)"
    )
