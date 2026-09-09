"""The ``/yoke do`` process-offer policy and chain budget.

Split from :mod:`yoke_core.api.routing_config`, which resolves where a
session runs (its lane and that lane's allowed actions). This module
answers a different question — whether an autonomous loop may dispatch a
process-backed action such as ``STRATEGIZE`` or ``FEED`` at all — and
reads its own keys from the same two scopes.

Project authority is the ``session-routing`` capability; machine
``~/.yoke/config.json`` is the fallback only when no project policy is
available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional

from yoke_core.api.routing_config import (
    PROCESS_OFFER_PREFIX as _PROCESS_OFFER_PREFIX,
    PROJECT_ROUTING_CAPABILITY,
    parse_config_file,
)


_PROCESS_OFFER_DEFAULT_KEY = f"{_PROCESS_OFFER_PREFIX}default"


_MAX_CHAIN_STEPS_DEFAULT = 3


_TRUTHY = {"true", "yes", "1", "on", "enabled"}
_FALSY = {"false", "no", "0", "off", "disabled"}


def _parse_bool(raw: Optional[str], default: bool) -> bool:
    """Parse the boolean form used by Yoke config.

    Recognized truthy strings (case-insensitive): ``true``, ``yes``, ``1``,
    ``on``, ``enabled``. Recognized falsy strings: ``false``, ``no``, ``0``,
    ``off``, ``disabled``. Anything else returns ``default`` so a typo in
    the config does not silently flip an autonomy gate.
    """
    if raw is None:
        return default
    folded = str(raw).strip().lower()
    if folded in _TRUTHY:
        return True
    if folded in _FALSY:
        return False
    return default


@dataclass(frozen=True)
class ProcessOfferPolicy:
    """Config-gated per-process-key dispatch policy for ``/yoke do``.

    ``/yoke do`` consults a config-backed policy before returning or dispatching
    a process-backed action (``STRATEGIZE``, ``FEED``, ``DOCTOR``, future).
    When a project policy is supplied, ``session-routing`` is the complete
    project authority.  Machine config is only the no-project fallback.

    The policy stores normalized lower-case process keys internally.
    Callers should pass the registry-canonical upper-case form
    (``"STRATEGIZE"``); :func:`is_enabled` / :func:`decision_for` /
    :func:`config_key_for` handle the case-folding themselves.
    """

    default_enabled: bool = False
    per_process: Dict[str, bool] = field(default_factory=dict)
    shared_project_per_process: Dict[str, bool] = field(default_factory=dict)
    shared_project_default: Optional[bool] = None
    shared_project_source: Optional[str] = None

    @staticmethod
    def _normalize(process_key: str) -> str:
        return process_key.strip().lower()

    def decision_for(self, process_key: str) -> "tuple[bool, str, str]":
        """Return ``(enabled, actionable_config_key, deciding_source)``.

        The key names the per-process knob whose flip changes the outcome
        at the deciding scope, spelled the way that scope stores it:
        ``process_offers.<key>`` in the capability document,
        ``do_process_offer_<key>`` in machine settings.
        """
        normalized = self._normalize(process_key)
        project_key = f"process_offers.{normalized}"
        machine_key = f"{_PROCESS_OFFER_PREFIX}{normalized}"
        shared_src = self.shared_project_source or (
            f"project capability {PROJECT_ROUTING_CAPABILITY}"
        )
        if normalized in self.shared_project_per_process:
            return (
                self.shared_project_per_process[normalized],
                project_key,
                shared_src,
            )
        if self.shared_project_default is not None:
            return self.shared_project_default, project_key, shared_src
        if normalized in self.per_process:
            return self.per_process[normalized], machine_key, "machine config"
        return self.default_enabled, machine_key, "machine config"

    def is_enabled(self, process_key: str) -> bool:
        return self.decision_for(process_key)[0]

    def config_key_for(self, process_key: str) -> str:
        """Return the actionable config key for the operator-facing surface."""
        return self.decision_for(process_key)[1]


def _offer_entries(raw: Dict[str, str]) -> "tuple[Optional[bool], Dict[str, bool]]":
    """Split one scope's raw settings into (default, per-process map)."""
    default: Optional[bool] = None
    if _PROCESS_OFFER_DEFAULT_KEY in raw:
        default = _parse_bool(raw.get(_PROCESS_OFFER_DEFAULT_KEY), default=False)
    per_process: Dict[str, bool] = {}
    for key, value in raw.items():
        if not key.startswith(_PROCESS_OFFER_PREFIX):
            continue
        suffix = key[len(_PROCESS_OFFER_PREFIX):]
        if not suffix or suffix == "default":
            continue
        per_process[suffix.lower()] = _parse_bool(value, default=False)
    return default, per_process


def load_process_offer_policy(
    config_path: str | Path,
    project_dir: "str | Path | None" = None,
    *,
    project_settings: Optional[Mapping[str, str]] = None,
    shared_project_source: Optional[str] = None,
) -> ProcessOfferPolicy:
    """Load the ``/yoke do`` process-offer policy.

    Machine scope reads ``config_path`` only when no DB project settings are
    supplied.  ``project_dir`` is accepted for old callers and ignored.
    """
    del project_dir
    raw = {} if project_settings is not None else parse_config_file(config_path)
    machine_default, per_process = _offer_entries(raw)
    shared_project_default: Optional[bool] = None
    shared_project_per_process: Dict[str, bool] = {}
    if project_settings is not None:
        shared_project_default, shared_project_per_process = _offer_entries(
            {str(k): str(v) for k, v in project_settings.items()}
        )
        shared_project_source = (
            shared_project_source
            or f"project capability {PROJECT_ROUTING_CAPABILITY}"
        )
    return ProcessOfferPolicy(
        default_enabled=(
            bool(machine_default) if machine_default is not None else False
        ),
        per_process=per_process,
        shared_project_per_process=shared_project_per_process,
        shared_project_default=shared_project_default,
        shared_project_source=shared_project_source,
    )


def get_max_chain_steps(config_path: str | Path) -> int:
    """Read ``max_chain_steps`` from config, defaulting to 3."""
    raw = parse_config_file(config_path)
    try:
        return int(raw.get("max_chain_steps", _MAX_CHAIN_STEPS_DEFAULT))
    except (ValueError, TypeError):
        return _MAX_CHAIN_STEPS_DEFAULT



__all__ = [
    "ProcessOfferPolicy",
    "get_max_chain_steps",
    "load_process_offer_policy",
]
