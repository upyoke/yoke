"""Command routes for connecting people and machines."""

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters import machine_admission, tokens

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
    ("tokens", "create"): ("profile.token.create", tokens.tokens_create),
    ("tokens", "list"): ("profile.get", tokens.tokens_list),
    ("tokens", "revoke"): ("profile.token.revoke", tokens.tokens_revoke),
}
