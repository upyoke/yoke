"""Compatibility imports for machine-local capability secret storage."""

from yoke_contracts.machine_config.capability_secret_store import (
    MachineCapabilitySecretError,
    list_machine_capability_secret_keys,
    machine_capability_secret_path,
    read_machine_capability_secret,
    store_machine_capability_secret,
)


__all__ = [
    "MachineCapabilitySecretError",
    "list_machine_capability_secret_keys",
    "machine_capability_secret_path",
    "read_machine_capability_secret",
    "store_machine_capability_secret",
]
