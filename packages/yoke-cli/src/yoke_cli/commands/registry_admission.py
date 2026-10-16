"""Command routes for connecting people and machines."""

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters import machine_admission

AdapterFn = Callable[[List[str]], int]

ADMISSION_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("machines", "pending"): (
        "machine_authorization.pending",
        machine_admission.machines_pending,
    ),
    ("machines", "approve"): (
        "machine_authorization.resolve",
        machine_admission.machines_approve,
    ),
    ("machines", "deny"): (
        "machine_authorization.resolve",
        machine_admission.machines_deny,
    ),
}
