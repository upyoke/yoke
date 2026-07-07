"""Helpers for Yoke session routing policy.

This module resolves three routing policy surfaces:

- executor -> default lane
- lane -> allowed downstream paths
- process key -> autonomous offer enabled/disabled

Project authority lives in the ``project_capabilities`` row whose type is
``session-routing``; machine ``~/.yoke/config.json`` remains the source-dev /
operator fallback when no project policy is available. Explicit test/operator
config fixtures may use the simple ``key=value`` format. Executor default-lane
keys may use a trailing ``*`` wildcard (for example
``executor_default_lane_claude*=DARIUS``) to cover every executor surface that
shares a prefix; specific override keys without ``*`` win against wildcard
defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Optional

from yoke_core.domain import json_helper
from yoke_core.domain.project_policy_capabilities import (
    SESSION_ROUTING_CAPABILITY as PROJECT_ROUTING_CAPABILITY,
    session_routing_defaults,
)
from yoke_core.domain import runtime_settings


_EXECUTOR_PREFIX = "executor_default_lane_"
_LANE_PATHS_PREFIX = "lane_paths_"
_PROCESS_OFFER_PREFIX = "do_process_offer_"
_PROCESS_OFFER_DEFAULT_KEY = f"{_PROCESS_OFFER_PREFIX}default"


def normalize_token(value: str) -> str:
    """Normalize executor/lane identifiers into config-key-safe tokens."""
    token = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return token.strip("_")


def _normalize_prefix_token(prefix: str) -> str:
    """Normalize a wildcard prefix while preserving meaningful trailing separators.

    Differs from :func:`normalize_token` in that it keeps a trailing underscore
    so ``claude_*`` and ``claude*`` remain distinct prefixes (the former only
    matches tokens with a separator after ``claude``; the latter also matches a
    bare ``claude`` token).
    """
    folded = re.sub(r"[^a-z0-9]+", "_", prefix.strip().lower())
    return folded.lstrip("_")


def parse_config_file(config_path: str | Path) -> Dict[str, str]:
    """Parse the Yoke ``key=value`` config file into a raw dict."""
    return runtime_settings.read_all(config_path=Path(config_path))


def _stringify_setting(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(part) for part in value)
    return str(value)


def _settings_to_raw_map(settings: Mapping[str, Any]) -> Dict[str, str]:
    """Normalize ``session-routing`` settings into the key/value grammar.

    The capability accepts either the existing flat keys directly or readable
    grouped aliases:

    - ``executor_default_lanes: {"claude*": "DARIUS"}``
    - ``lane_paths: {"DARIUS": ["shepherd", "conduct"]}``
    - ``process_offers: {"default": false, "feed": true}``
    """
    raw: Dict[str, str] = {}
    for key, value in settings.items():
        if key == "executor_default_lanes" and isinstance(value, Mapping):
            for executor, lane in value.items():
                raw[f"{_EXECUTOR_PREFIX}{executor}"] = _stringify_setting(lane)
            continue
        if key == "lane_paths" and isinstance(value, Mapping):
            for lane, paths in value.items():
                raw[f"{_LANE_PATHS_PREFIX}{lane}"] = _stringify_setting(paths)
            continue
        if key in {"process_offer", "process_offers"} and isinstance(value, Mapping):
            for process, enabled in value.items():
                raw[f"{_PROCESS_OFFER_PREFIX}{process}"] = _stringify_setting(enabled)
            continue
        raw[str(key)] = _stringify_setting(value)
    return raw


def _loads_settings_object(settings_text: object) -> Dict[str, str]:
    if not settings_text:
        return {}
    if isinstance(settings_text, Mapping):
        return _settings_to_raw_map(settings_text)
    if not isinstance(settings_text, str):
        return {}
    try:
        parsed = json_helper.loads_text(settings_text)
    except Exception:
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    return _settings_to_raw_map(parsed)


def load_project_routing_settings(
    conn: Any,
    project_id: int | None,
) -> Dict[str, str]:
    """Read project-scoped routing policy from ``project_capabilities``.

    Missing rows return source defaults: once a project id is known, local
    machine config is not a routing-policy authority.
    """
    if conn is None or project_id is None:
        return {}
    try:
        row = conn.execute(
            "SELECT COALESCE(settings, '{}') FROM project_capabilities "
            "WHERE project_id=%s AND type=%s",
            (int(project_id), PROJECT_ROUTING_CAPABILITY),
        ).fetchone()
    except Exception:
        _rollback_quietly(conn)
        return _settings_to_raw_map(session_routing_defaults())
    if row is None:
        return _settings_to_raw_map(session_routing_defaults())
    try:
        settings_text = row["settings"]
    except (KeyError, TypeError):
        settings_text = row[0]
    raw = _settings_to_raw_map(session_routing_defaults())
    raw.update(_loads_settings_object(settings_text))
    return raw


def _rollback_quietly(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _routing_config_from_raw(raw: Mapping[str, str]) -> "RoutingConfig":
    executor_defaults: Dict[str, str] = {}
    executor_wildcard_lanes: Dict[str, str] = {}
    lane_paths: Dict[str, List[str]] = {}

    for key, value in raw.items():
        if key.startswith(_EXECUTOR_PREFIX):
            executor_key = key[len(_EXECUTOR_PREFIX):]
            if not executor_key or not value:
                continue
            if "*" in executor_key:
                # Only the trailing-``*`` wildcard form is supported. Any other
                # placement (mid-string, leading) is permissively ignored so a
                # malformed line cannot crash session offer.
                if not executor_key.endswith("*"):
                    continue
                prefix = _normalize_prefix_token(executor_key[:-1])
                executor_wildcard_lanes[prefix] = value.strip()
                continue
            executor_defaults[normalize_token(executor_key)] = value.strip()
            continue

        if key.startswith(_LANE_PATHS_PREFIX):
            lane_key = key[len(_LANE_PATHS_PREFIX):]
            if not lane_key:
                continue
            parsed_paths = [part.strip().lower() for part in value.split(",") if part.strip()]
            lane_paths[normalize_token(lane_key).upper()] = parsed_paths

    return RoutingConfig(
        executor_default_lanes=executor_defaults,
        executor_wildcard_lanes=executor_wildcard_lanes,
        lane_allowed_paths=lane_paths,
    )


@dataclass(frozen=True)
class RoutingConfig:
    """Resolved Yoke-global routing policy."""

    executor_default_lanes: Dict[str, str] = field(default_factory=dict)
    executor_wildcard_lanes: Dict[str, str] = field(default_factory=dict)
    lane_allowed_paths: Dict[str, List[str]] = field(default_factory=dict)

    def default_lane_for_executor(self, executor: str) -> str:
        """Return the configured default lane for an executor.

        Resolution order:
          1. Exact key match (``executor_default_lane_<token>``).
          2. Wildcard match — among ``executor_default_lane_*`` keys whose
             non-wildcard prefix is a prefix of the normalized executor token,
             the longest prefix wins. Ties are broken by alphabetical order
             of the prefix for determinism.
          3. Global ``executor_default_lane_unknown`` key.
          4. Hardcoded ``"primary"`` sentinel — sessions opt out of lane-aware
             scheduling when no config keys match.
        """
        token = normalize_token(executor)
        if token in self.executor_default_lanes:
            return self.executor_default_lanes[token]

        matched_prefix: Optional[str] = None
        for prefix in self.executor_wildcard_lanes:
            if not token.startswith(prefix):
                continue
            if matched_prefix is None:
                matched_prefix = prefix
                continue
            if len(prefix) > len(matched_prefix) or (
                len(prefix) == len(matched_prefix) and prefix < matched_prefix
            ):
                matched_prefix = prefix
        if matched_prefix is not None:
            return self.executor_wildcard_lanes[matched_prefix]

        if "unknown" in self.executor_default_lanes:
            return self.executor_default_lanes["unknown"]
        return "primary"


def load_routing_config(
    config_path: str | Path,
    *,
    project_settings: Optional[Mapping[str, str]] = None,
) -> RoutingConfig:
    """Load executor default lanes and lane allowlists.

    Machine config is the no-project fallback.  When project settings are
    supplied from the ``session-routing`` capability, they are the complete
    project routing authority.
    """
    raw = {} if project_settings is not None else parse_config_file(config_path)
    if project_settings is not None:
        raw.update({str(k): str(v) for k, v in project_settings.items()})
    return _routing_config_from_raw(raw)


def resolve_execution_lane(
    *,
    executor: str,
    explicit_lane: Optional[str],
    routing_config: RoutingConfig,
) -> str:
    """Resolve the lane for a session offer.

    Explicit non-empty lane wins, except the sentinel ``default`` which means
    "use the executor default lane". Otherwise, use the executor default from
    Yoke core config. Unknown executors fall back to ``primary``.
    """
    if explicit_lane and explicit_lane.strip():
        resolved = explicit_lane.strip()
        if normalize_token(resolved) != "default":
            return resolved
    return routing_config.default_lane_for_executor(executor)


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

        The key is always the per-process ``do_process_offer_<key>`` —
        the knob whose flip changes the outcome at the deciding scope
        (the per-process key outranks that scope's default). The source
        names the project capability when project policy decided, else
        ``"machine config"``.
        """
        normalized = self._normalize(process_key)
        actionable = f"{_PROCESS_OFFER_PREFIX}{normalized}"
        shared_src = self.shared_project_source or (
            f"project capability {PROJECT_ROUTING_CAPABILITY}"
        )
        if normalized in self.shared_project_per_process:
            return (
                self.shared_project_per_process[normalized],
                actionable,
                shared_src,
            )
        if self.shared_project_default is not None:
            return self.shared_project_default, actionable, shared_src
        if normalized in self.per_process:
            return self.per_process[normalized], actionable, "machine config"
        return self.default_enabled, actionable, "machine config"

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


def config_path_from_db_path(db_path: str | Path) -> Path:
    """Return the legacy fixture config path adjacent to an explicit test DB."""
    return Path(db_path).resolve().parent / "config"


def _cli_resolve_lane(args) -> int:
    """``python3 -m yoke_core.api.routing_config resolve-lane`` — print default lane.

    Used by skill shell wrappers that previously hand-rolled ``grep`` against
    the config file (e.g. ``do/loop.md``). Centralizing the lookup keeps the
    exact -> wildcard -> ``unknown`` -> ``primary`` chain in one place.
    """
    cfg = load_routing_config(args.config)
    print(cfg.default_lane_for_executor(args.executor))
    return 0


def main() -> int:
    """CLI entry point for skill wrappers."""
    import argparse

    parser = argparse.ArgumentParser(prog="routing_config")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("resolve-lane", help="Print default lane for an executor")
    p.add_argument("--config", required=True, help="Path to Yoke config")
    p.add_argument("--executor", required=True, help="Executor identifier")

    args = parser.parse_args()
    if args.command == "resolve-lane":
        return _cli_resolve_lane(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
