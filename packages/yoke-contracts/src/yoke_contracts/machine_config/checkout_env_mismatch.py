"""Explain a checkout that is mapped only under a different connection env.

Project ids are numbered per universe, so a checkout→project mapping is
recorded per env and deliberately does not resolve across universes. When
the selected env has no row for the checkout, callers that need a project
id refuse. That refusal is correct, but "this checkout has no configured
project id" reads as *unconfigured* when the real state is *configured
somewhere else* — the operator connected to another universe and the
mapping stayed behind.

This module turns that state into a named diagnostic: which env is
selected, which env the checkout is actually registered under, and the two
supported ways forward (select the registered env, or register the
checkout under the selected one). It never falls back across universes,
never registers anything, and never changes what resolves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config.schema_connections import (
    ENV_OVERRIDE,
    MachineConfigContractError,
    selected_env,
)
from yoke_contracts.machine_config.schema_projects import (
    checkout_path_candidates,
    entry_resolves_under_env,
    normalize_projects,
)

UNTAGGED_ENV_LABEL = "(untagged)"
MISMATCH_PREFIX = "Checkout env mismatch:"


def _path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve())
    except OSError:
        return str(path.expanduser())


def _entry_env_label(entry: Mapping[str, Any], active_env: str) -> str:
    """The env an entry belongs to, for display.

    An untagged legacy row carries no env of its own; it resolves under
    ``active_env``, so that is the env to name. With no active env
    configured there is nothing truthful to name, and the row is labelled
    as untagged.
    """
    raw = entry.get("env")
    label = str(raw).strip() if isinstance(raw, str) else ""
    return label or active_env or UNTAGGED_ENV_LABEL


def other_env_mappings(
    payload: Mapping[str, Any],
    repo_root: str | Path,
) -> list[dict[str, Any]]:
    """Return this checkout's mappings that do not resolve under the selected env.

    Mirrors :func:`schema_projects.project_entry_for_checkout` resolution and
    returns the complement, so a caller can only ever report an env the
    checkout is genuinely registered under.
    """
    try:
        env: str | None = selected_env(payload)
    except MachineConfigContractError:
        env = None
    active = str(payload.get("active_env") or "").strip()
    candidates = {_path_key(path) for path in checkout_path_candidates(repo_root)}
    return [
        entry
        for entry in normalize_projects(payload.get("projects"))
        if _path_key(Path(entry["checkout"])) in candidates
        and not entry_resolves_under_env(entry, env=env, active_env=active)
    ]


def selected_env_label(payload: Mapping[str, Any]) -> str:
    """Selected env for display, or an explicit unresolved marker."""
    try:
        return selected_env(payload)
    except MachineConfigContractError:
        return "(unresolved)"


def mismatch_note_for_payload(
    payload: Mapping[str, Any],
    repo_root: str | Path,
) -> str | None:
    """Diagnose a checkout registered only under another env, or ``None``.

    ``None`` means the checkout is genuinely unmapped on this machine, so
    the caller's own "not configured" wording stays accurate.
    """
    others = other_env_mappings(payload, repo_root)
    if not others:
        return None
    active = str(payload.get("active_env") or "").strip()
    labels = [_entry_env_label(entry, active) for entry in others]
    registered = ", ".join(
        f"project {entry['project_id']} on env {label}"
        for entry, label in zip(others, labels)
    )
    named = sorted({label for label in labels if label != UNTAGGED_ENV_LABEL})
    checkout = Path(repo_root).expanduser()
    selected = selected_env_label(payload)
    switch = ""
    if named:
        target = named[0] if len(named) == 1 else "<env>"
        switch = (
            f"Either select the registered env (`yoke env use {target}`, or "
            f"{ENV_OVERRIDE}={target} for one command), or register"
        )
    return (
        f"{MISMATCH_PREFIX} checkout {checkout} is registered as "
        f"{registered}, but the selected env is {selected}, and project ids "
        f"do not resolve across universes. {switch or 'Register'} this "
        f"checkout under {selected} with `yoke project register {checkout} "
        "--project-id N` using that universe's own project id."
    )


def mismatch_note(
    repo_root: str | Path,
    *,
    config_path: str | Path | None = None,
) -> str | None:
    """Load machine config and diagnose the checkout, or ``None``.

    Config read failures resolve to ``None`` so a diagnostic can never turn
    a refusal into a crash.
    """
    from yoke_contracts.machine_config import runtime

    try:
        payload = runtime.load_config(config_path)
    except Exception:  # noqa: BLE001 — a hint must never break the refusal
        return None
    try:
        return mismatch_note_for_payload(payload, repo_root)
    except Exception:  # noqa: BLE001 — same
        return None


def with_mismatch_note(
    message: str,
    repo_root: str | Path,
    *,
    config_path: str | Path | None = None,
) -> str:
    """Append the diagnostic to ``message`` when one applies."""
    note = mismatch_note(repo_root, config_path=config_path)
    return f"{message} {note}" if note else message


__all__ = [
    "MISMATCH_PREFIX",
    "UNTAGGED_ENV_LABEL",
    "mismatch_note",
    "mismatch_note_for_payload",
    "other_env_mappings",
    "selected_env_label",
    "with_mismatch_note",
]
