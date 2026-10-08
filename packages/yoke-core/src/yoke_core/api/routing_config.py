"""Helpers for Yoke session routing policy.

This module resolves where a session runs:

- session (harness, model) -> level, through ``level_rules`` selectors
  and the ``executor_default_levels`` harness default beneath them
- level -> its operator-facing label and glyph

Project authority lives in the ``project_capabilities`` row whose type is
``session-routing``; machine ``~/.yoke/config.json`` remains the source-dev /
operator fallback when no project policy is available. Explicit test/operator
config fixtures may use the simple ``key=value`` format. Executor default-level
keys may use a trailing ``*`` wildcard (for example
``executor_default_level_claude*=DARIUS``) to cover every executor surface that
shares a prefix; specific override keys without ``*`` win against wildcard
defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Optional, Tuple

from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL
from yoke_core.domain.session_routing_rules import (
    LevelRule,
    parse_level_rules_for_routing,
    resolve_rule_level,
)
from yoke_contracts.session_level import EXECUTOR_DEFAULT_LEVEL_PREFIX
from yoke_core.domain import json_helper
from yoke_core.domain.project_policy_capabilities import (
    SESSION_ROUTING_CAPABILITY as PROJECT_ROUTING_CAPABILITY,
    session_routing_defaults,
)
from yoke_core.domain import runtime_settings


_EXECUTOR_PREFIX = EXECUTOR_DEFAULT_LEVEL_PREFIX

# Settings whose value is a nested document rather than a scalar. The
# key/value grammar the rest of this module speaks cannot carry one, so
# they ride through it as JSON text and are parsed back below.
_JSON_VALUED_KEYS = ("level_rules", "level_metadata")


def normalize_token(value: str) -> str:
    """Normalize executor/level identifiers into config-key-safe tokens."""
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

    - ``executor_default_levels: {"claude*": "DARIUS"}``

    ``level_rules`` and ``level_metadata`` are nested documents that the
    flat grammar cannot express, so they are carried as JSON text.
    """
    raw: Dict[str, str] = {}
    for key, value in settings.items():
        if key in _JSON_VALUED_KEYS:
            raw[str(key)] = (
                value if isinstance(value, str) else json_helper.dumps_compact(value)
            )
            continue
        if key == "executor_default_levels" and isinstance(value, Mapping):
            for executor, level in value.items():
                raw[f"{_EXECUTOR_PREFIX}{executor}"] = _stringify_setting(level)
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
    executor_wildcard_levels: Dict[str, str] = {}

    for key, value in raw.items():
        if key.startswith(_EXECUTOR_PREFIX):
            executor_key = key[len(_EXECUTOR_PREFIX) :]
            if not executor_key or not value:
                continue
            if "*" in executor_key:
                # Only the trailing-``*`` wildcard form is supported. Any other
                # placement (mid-string, leading) is permissively ignored so a
                # malformed line cannot crash session registration.
                if not executor_key.endswith("*"):
                    continue
                prefix = _normalize_prefix_token(executor_key[:-1])
                executor_wildcard_levels[prefix] = value.strip()
                continue
            executor_defaults[normalize_token(executor_key)] = value.strip()
            continue

    return RoutingConfig(
        executor_default_levels=executor_defaults,
        executor_wildcard_levels=executor_wildcard_levels,
        level_rules=parse_level_rules_for_routing(_json_setting(raw, "level_rules")),
        level_metadata=_json_setting(raw, "level_metadata") or {},
    )


@dataclass(frozen=True)
class RoutingConfig:
    """Resolved Yoke-global routing policy."""

    executor_default_levels: Dict[str, str] = field(default_factory=dict)
    executor_wildcard_levels: Dict[str, str] = field(default_factory=dict)
    level_rules: Tuple[LevelRule, ...] = ()
    level_metadata: Mapping[str, Any] = field(default_factory=dict)

    def default_level_for_executor(self, executor: str) -> str:
        """Return the configured default level for an executor.

        Resolution order:
          1. Exact key match (``executor_default_level_<token>``).
          2. Wildcard match — among ``executor_default_level_*`` keys whose
             non-wildcard prefix prefixes the normalized executor token, the
             longest wins; ties break alphabetically for determinism.
          3. Global ``executor_default_level_unknown`` key.
          4. The unresolved sentinel — no config key matched at all.
        """
        token = normalize_token(executor)
        if token in self.executor_default_levels:
            return self.executor_default_levels[token]

        matched_prefix: Optional[str] = None
        for prefix in self.executor_wildcard_levels:
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
            return self.executor_wildcard_levels[matched_prefix]

        if "unknown" in self.executor_default_levels:
            return self.executor_default_levels["unknown"]
        return UNRESOLVED_EXECUTION_LEVEL

    def level_for_session(self, *, executor: str, model: Optional[str] = None) -> str:
        """Return the level a session with these facts routes onto.

        A ``level_rules`` selector wins over the harness default, because
        every selector is narrower than "any session on this harness";
        :mod:`yoke_core.domain.session_routing_rules` owns which of
        several matching selectors is narrowest. With no rules
        configured this is exactly the harness default, which is how a
        project that has never declared a rule keeps its behaviour.
        """
        matched = resolve_rule_level(self.level_rules, executor=executor, model=model)
        if matched is not None:
            return matched
        return self.default_level_for_executor(executor)


def load_routing_config(
    config_path: str | Path,
    *,
    project_settings: Optional[Mapping[str, str]] = None,
) -> RoutingConfig:
    """Load executor default levels, level rules, and presentation metadata.

    Machine config is the no-project fallback.  When project settings are
    supplied from the ``session-routing`` capability, they are the complete
    project routing authority.

    Supplied settings pass through the same normalizer the DB read uses, so
    the grouped capability shape and the flat key/value grammar mean the
    same thing here. Stringifying them instead would silently flatten the
    nested documents — ``level_rules`` most visibly — into a Python repr no
    reader can parse, and the caller would get a session routed by the
    harness default with nothing said about why.
    """
    raw = {} if project_settings is not None else parse_config_file(config_path)
    if project_settings is not None:
        raw.update(_settings_to_raw_map(project_settings))
    return _routing_config_from_raw(raw)


def resolve_execution_level(
    *,
    executor: str,
    explicit_level: Optional[str],
    routing_config: RoutingConfig,
    model: Optional[str] = None,
) -> str:
    """Resolve the grouping for a registering session.

    An explicit level wins only when it names a real choice: ``default`` and
    the unresolved sentinel both mean "nothing chose a level" and yield to
    routing policy, so a caller that could not resolve one locally cannot
    overrule the project's mapping with an unresolved grouping.

    ``model`` is the model the session is actually serving, and it is
    what ``level_rules`` model selectors match against. Omitting it is
    the honest answer when nothing attested one, and leaves the session
    to the harness tiers rather than guessing a model for it.
    """
    if explicit_level and explicit_level.strip():
        resolved = explicit_level.strip()
        if normalize_token(resolved) not in ("default", UNRESOLVED_EXECUTION_LEVEL):
            return resolved
    return routing_config.level_for_session(executor=executor, model=model)


def config_path_from_db_path(db_path: str | Path) -> Path:
    """Return the legacy fixture config path adjacent to an explicit test DB."""
    return Path(db_path).resolve().parent / "config"
