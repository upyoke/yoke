"""Read the accounts a project declares for a Test Machine browser approval.

A browser approval may stop at Google's account chooser; the driver picks the
account the project's browser identities declare for the approval origin
(``yoke_harness.machine_account_chooser``). The declarations are read from
the control plane here, on the workstation that runs the case, and only for
cases with a ``machine_browser_approval`` gate.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    parse_identity_declarations,
)
from yoke_contracts.machine_config.capability_secrets import (
    BROWSER_CONTROL_CAPABILITY,
)
from yoke_harness.machine_account_chooser import DeclaredAccounts, declared_accounts

from yoke_core.domain.machine_qa_operator_gate_contract import (
    MACHINE_BROWSER_APPROVAL,
)


def needs_browser_approval(method_config: Any) -> bool:
    """Whether any action in the config, at any depth, approves in a browser."""
    if isinstance(method_config, dict):
        return method_config.get("operator_gate") == MACHINE_BROWSER_APPROVAL or any(
            needs_browser_approval(value) for value in method_config.values()
        )
    if isinstance(method_config, list):
        return any(needs_browser_approval(value) for value in method_config)
    return False


def read_declared_accounts(project: str) -> DeclaredAccounts:
    """Read the declarations; an unreadable answer is named, never guessed."""
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id="projects.capability_settings.get",
        target=TargetRef(kind="global"),
        payload={"project": project, "cap_type": BROWSER_CONTROL_CAPABILITY},
    )
    if not response.success:
        if response.error is not None and response.error.code == "not_found":
            return DeclaredAccounts()
        detail = response.error.message if response.error else "no settings returned"
        return DeclaredAccounts(
            unavailable=(
                "browser_identity_declarations_unreadable: could not read "
                f"project {project!r} browser-control settings: {detail}. Check "
                "the control plane with `yoke env list`, then rerun the case."
            )
        )
    raw = (response.result or {}).get("settings_json") or "{}"
    try:
        settings = json.loads(raw) if isinstance(raw, str) else raw
        return declared_accounts(
            parse_identity_declarations(settings if isinstance(settings, dict) else {})
        )
    except (ValueError, BrowserIdentityError) as exc:
        return DeclaredAccounts(
            unavailable=(
                f"browser_identity_declarations_unreadable: {exc}. Repair them "
                "with `yoke projects capability-settings set`, then rerun."
            )
        )


def case_declared_accounts(
    project: str, method_configs: Iterable[Any]
) -> DeclaredAccounts:
    """Read declarations only when one of the cases approves in a browser."""
    if any(needs_browser_approval(config) for config in method_configs):
        return read_declared_accounts(project)
    return DeclaredAccounts()


def operator_approval_targets(
    contract: Any,
) -> tuple[tuple[str, ...], DeclaredAccounts]:
    """The origins a contract's gates may approve on, and the declared accounts."""
    allowed_urls = tuple(
        str(value).rstrip("/")
        for case in contract.cases
        for key, value in case.execution_target["endpoints"].items()
        if key.endswith("_url") and isinstance(value, str) and value
    )
    return allowed_urls, case_declared_accounts(
        contract.project, (case.method_config for case in contract.cases)
    )


__all__ = [
    "case_declared_accounts",
    "needs_browser_approval",
    "operator_approval_targets",
    "read_declared_accounts",
]
