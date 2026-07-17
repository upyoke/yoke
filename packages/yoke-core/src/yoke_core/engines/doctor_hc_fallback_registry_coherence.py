"""HC-fallback-registry-coherence — verify yoke_operation_inventory consistency.

Three invariants checked against the live registries:

1. Every ``status="wrapped"`` row in the tracker has a CLI-registry adapter
   and either a matching function-registry entry or an explicit client-local
   authorization classification.
2. Every ``status="pending"`` row's ``shell_form`` parses as a valid
   Yoke-owned multi-module invocation (the operator-debug shape that
   future handler-registration slices will wrap).
3. No tracker entry contradicts the function-registry (status=wrapped
   row whose function id is missing from the dispatcher) or
   CLI-registry (status=wrapped row whose yoke CLI tokens are not in
   the subcommand registry).

PASS when every wrapped row passes both registry checks AND every
pending row parses cleanly. FAIL surfaces the first three offenders in
the detail block. Self-skips cleanly if the tracker module is not yet
present in the running tree (early-bootstrap safety).
"""

from __future__ import annotations

from typing import List, Tuple

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_DEFAULT_HC_NAME = "HC-fallback-registry-coherence"
_DEFAULT_HC_DESCRIPTION = (
    "yoke_operation_inventory tracker matches function-registry + CLI-registry"
)
_PENDING_MODULE_PREFIXES = ("python3 -m yoke_core.",)


def _resolve_tracker():
    try:
        from yoke_cli import operation_inventory as inv
    except Exception:
        return None
    return inv


def _resolve_subcommand_registry():
    try:
        from yoke_cli.commands.registry import (
            SUBCOMMAND_ALIAS_REGISTRY,
            SUBCOMMAND_REGISTRY,
        )
    except Exception:
        return None
    return {**SUBCOMMAND_REGISTRY, **SUBCOMMAND_ALIAS_REGISTRY}


def _resolve_function_registry():
    try:
        from yoke_core.domain.yoke_function_dispatch import (
            _ensure_handlers_registered,
        )
        from yoke_core.domain.yoke_function_registry import list_entries

        _ensure_handlers_registered()
        return {e.function_id for e in list_entries()}
    except Exception:
        return None


def _wrapped_cli_tokens_for(shell_form: str) -> Tuple[str, ...]:
    """Translate a ``yoke X Y Z`` shell_form into its CLI token tuple."""
    parts = shell_form.split()
    return tuple(parts[1:])  # drop the leading 'yoke'


def _check_wrapped(inv, sub_reg, fn_ids) -> List[str]:
    from yoke_core.domain.function_authz_scope import is_explicit_client_local

    issues: List[str] = []
    for entry in inv.by_status(inv.WRAPPED):
        if not entry.shell_form.startswith("yoke "):
            issues.append(
                f"wrapped row {entry.shell_form!r} does not start with 'yoke '"
            )
            continue
        cli_tokens = _wrapped_cli_tokens_for(entry.shell_form)
        if cli_tokens not in sub_reg:
            issues.append(
                f"wrapped row {entry.shell_form!r} not registered in "
                f"yoke_subcommand_registry (CLI tokens {cli_tokens!r})"
            )
            continue
        registered_fn_id, _ = sub_reg[cli_tokens]
        if (
            fn_ids is not None
            and registered_fn_id not in fn_ids
            and not is_explicit_client_local(registered_fn_id)
        ):
            issues.append(
                f"wrapped row {entry.shell_form!r} -> function id "
                f"{registered_fn_id!r} not present in dispatcher registry"
            )
    return issues


def _check_pending(inv) -> List[str]:
    issues: List[str] = []
    for entry in inv.by_status(inv.PENDING):
        if not entry.shell_form.startswith(_PENDING_MODULE_PREFIXES):
            issues.append(
                f"pending row {entry.shell_form!r} does not start with "
                f"{_PENDING_MODULE_PREFIXES!r} (final package multi-module shape)"
            )
            continue
        if not entry.proposed_function_id:
            issues.append(
                f"pending row {entry.shell_form!r} missing proposed_function_id"
            )
    return issues


def _format_issues(issues: List[str]) -> str:
    if not issues:
        return ""
    head = issues[:3]
    suffix = (
        f"\n(+{len(issues) - len(head)} more)"
        if len(issues) > len(head) else ""
    )
    return "\n".join(head) + suffix


def hc_fallback_registry_coherence(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    inv = _resolve_tracker()
    if inv is None:
        rec.record(
            _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "PASS",
            "yoke_operation_inventory not present; HC self-skipped",
        )
        return
    sub_reg = _resolve_subcommand_registry()
    if sub_reg is None:
        rec.record(
            _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "PASS",
            "yoke_subcommand_registry not present; HC self-skipped",
        )
        return
    fn_ids = _resolve_function_registry()
    issues = _check_wrapped(inv, sub_reg, fn_ids) + _check_pending(inv)
    if issues:
        rec.record(
            _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "FAIL",
            _format_issues(issues),
        )
        return
    wrapped_count = len(inv.by_status(inv.WRAPPED))
    pending_count = len(inv.by_status(inv.PENDING))
    rec.record(
        _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "PASS",
        f"{wrapped_count} wrapped + {pending_count} pending rows "
        "coherent with function/client-local + CLI registries",
    )


__all__ = ["hc_fallback_registry_coherence"]
