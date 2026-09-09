"""Helpers for Yoke session routing policy.

This module resolves where a session runs:

- session (harness, model) -> lane, through ``lane_rules`` selectors
  and the ``executor_default_lanes`` harness default beneath them
- lane -> allowed actions
- lane -> its operator-facing label and glyph

Whether an autonomous loop may dispatch a process at all is a separate
question, answered by :mod:`yoke_core.api.process_offer_policy`.

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
from typing import Any, Dict, List, Mapping, Optional, Tuple

from yoke_contracts.session_lane import UNRESOLVED_EXECUTION_LANE
from yoke_core.domain.session_routing_rules import (
    LaneRule,
    parse_lane_rules_for_routing,
    resolve_rule_lane,
)
from yoke_core.domain import json_helper
from yoke_core.domain.project_policy_capabilities import (
    SESSION_ROUTING_CAPABILITY as PROJECT_ROUTING_CAPABILITY,
    session_routing_defaults,
)
from yoke_core.domain import runtime_settings


_EXECUTOR_PREFIX = "executor_default_lane_"
_LANE_PATHS_PREFIX = "lane_paths_"
PROCESS_OFFER_PREFIX = "do_process_offer_"

# Settings whose value is a nested document rather than a scalar. The
# key/value grammar the rest of this module speaks cannot carry one, so
# they ride through it as JSON text and are parsed back below.
_JSON_VALUED_KEYS = ("lane_rules", "lane_metadata")


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

    ``lane_rules`` and ``lane_metadata`` are nested documents that the
    flat grammar cannot express, so they are carried as JSON text.
    """
    raw: Dict[str, str] = {}
    for key, value in settings.items():
        if key in _JSON_VALUED_KEYS:
            raw[str(key)] = json_helper.dumps_compact(value)
            continue
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
                raw[f"{PROCESS_OFFER_PREFIX}{process}"] = _stringify_setting(enabled)
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


def _json_setting(raw: Mapping[str, str], key: str) -> Any:
    """Read one nested setting back out of the flat grammar.

    Unparseable text yields ``None`` so a hand-edited document degrades
    to the harness default instead of refusing every session in the
    project; the settings write boundary is where malformed content is
    refused by name.
    """
    text = raw.get(key)
    if not text:
        return None
    if not isinstance(text, str):
        return text
    try:
        return json_helper.loads_text(text)
    except Exception:
        return None


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
        lane_rules=parse_lane_rules_for_routing(_json_setting(raw, "lane_rules")),
        lane_metadata=_json_setting(raw, "lane_metadata") or {},
    )


@dataclass(frozen=True)
class RoutingConfig:
    """Resolved Yoke-global routing policy."""

    executor_default_lanes: Dict[str, str] = field(default_factory=dict)
    executor_wildcard_lanes: Dict[str, str] = field(default_factory=dict)
    lane_allowed_paths: Dict[str, List[str]] = field(default_factory=dict)
    lane_rules: Tuple[LaneRule, ...] = ()
    lane_metadata: Mapping[str, Any] = field(default_factory=dict)

    def default_lane_for_executor(self, executor: str) -> str:
        """Return the configured default lane for an executor.

        Resolution order:
          1. Exact key match (``executor_default_lane_<token>``).
          2. Wildcard match — among ``executor_default_lane_*`` keys whose
             non-wildcard prefix prefixes the normalized executor token, the
             longest wins; ties break alphabetically for determinism.
          3. Global ``executor_default_lane_unknown`` key.
          4. The unresolved sentinel — no config key matched at all.
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
        return UNRESOLVED_EXECUTION_LANE

    def lane_for_session(
        self, *, executor: str, model: Optional[str] = None
    ) -> str:
        """Return the lane a session with these facts routes onto.

        A ``lane_rules`` selector wins over the harness default, because
        every selector is narrower than "any session on this harness";
        :mod:`yoke_core.domain.session_routing_rules` owns which of
        several matching selectors is narrowest. With no rules
        configured this is exactly the harness default, which is how a
        project that has never declared a rule keeps its behaviour.
        """
        matched = resolve_rule_lane(
            self.lane_rules, executor=executor, model=model
        )
        if matched is not None:
            return matched
        return self.default_lane_for_executor(executor)


def load_routing_config(
    config_path: str | Path,
    *,
    project_settings: Optional[Mapping[str, str]] = None,
) -> RoutingConfig:
    """Load executor default lanes, lane allowlists, and lane rules.

    Machine config is the no-project fallback.  When project settings are
    supplied from the ``session-routing`` capability, they are the complete
    project routing authority.

    Supplied settings pass through the same normalizer the DB read uses, so
    the grouped capability shape and the flat key/value grammar mean the
    same thing here. Stringifying them instead would silently flatten the
    nested documents — ``lane_rules`` most visibly — into a Python repr no
    reader can parse, and the caller would get a session routed by the
    harness default with nothing said about why.
    """
    raw = {} if project_settings is not None else parse_config_file(config_path)
    if project_settings is not None:
        raw.update(_settings_to_raw_map(project_settings))
    return _routing_config_from_raw(raw)


def resolve_execution_lane(
    *,
    executor: str,
    explicit_lane: Optional[str],
    routing_config: RoutingConfig,
    model: Optional[str] = None,
) -> str:
    """Resolve the lane for a session offer or registration.

    An explicit lane wins only when it names a real choice: ``default`` and
    the unresolved sentinel both mean "nothing chose a lane" and yield to
    routing policy, so a caller that could not resolve one locally cannot
    overrule the project's mapping with a lane no allowlist declares.

    ``model`` is the model the session is actually serving, and it is
    what ``lane_rules`` model selectors match against. Omitting it is
    the honest answer when nothing attested one, and leaves the session
    to the harness tiers rather than guessing a model for it.
    """
    if explicit_lane and explicit_lane.strip():
        resolved = explicit_lane.strip()
        if normalize_token(resolved) not in ("default", UNRESOLVED_EXECUTION_LANE):
            return resolved
    return routing_config.lane_for_session(executor=executor, model=model)


def config_path_from_db_path(db_path: str | Path) -> Path:
    """Return the legacy fixture config path adjacent to an explicit test DB."""
    return Path(db_path).resolve().parent / "config"
