"""Project-local board settings parser."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, field
from pathlib import Path
from typing import Any, Dict, Mapping

from yoke_contracts.project_contract.board_art.config_paths import board_config_path


@dataclass
class BoardConfig:
    """Parsed project-local board configuration."""

    # -- dashboard widget toggles (true = show) --------------------------------
    dashboard_velocity: bool = True
    dashboard_weather: bool = True
    dashboard_types: bool = True
    dashboard_age: bool = True
    dashboard_badges: bool = True
    dashboard_recent_sessions: bool = True
    dashboard_sessions_scope: str = ""  # empty = board scope; all = global
    dashboard_velocity_meter: bool = False
    done_section_limit: int = 250

    # -- timeline widget ------------------------------------------------------
    timeline_widget: str = "idle"  # always | never | idle
    timeline_scope: str = ""       # empty = board scope; all = global
    timeline_label_days: int = 0   # labels window in days; 0 = all-time
    timeline_label_df_cap_pct: int = 0  # drop labels w/ doc-freq > N% (0 = off)
    timeline_extra_stopwords: str = ""  # comma-sep extra stopwords
    timeline_label_min: int = 0    # widen window until at least N labels (0 = off)

    # -- art frontier fill ----------------------------------------------------
    art_frontier_since: int = 0  # item-id threshold; 0 = all items

    # -- stats box ------------------------------------------------------------
    dashboard_meter_cap: int = 50  # proportional meter denominator

    # -- art override ---------------------------------------------------------
    art_override: str = ""  # force a specific variant name

    # -- bucket weights (relative, not percentage) ----------------------------
    art_weight_rainbow: int = 20
    art_weight_emoji: int = 20
    art_weight_ascii: int = 20
    art_weight_mixed: int = 20
    art_weight_frontier: int = 50

    # -- rainbow sub-mode weights ---------------------------------------------
    # When any key is present, per-variant mode activates for rainbow;
    # unset sub-modes become weight 0.
    art_weight_rainbow_random: int = 0
    art_weight_rainbow_letters: int = 0
    art_weight_rainbow_halves: int = 0
    art_weight_rainbow_gradient: int = 0
    art_weight_rainbow_emoji: int = 0

    # -- extra rainbow sub-mode weights (catch-all) ---------------------------
    rainbow_sub_weights: Dict[str, int] = field(default_factory=dict)

    @property
    def rainbow_per_variant_mode(self) -> bool:
        """True when any rainbow sub-mode weight was explicitly set."""
        return bool(self.rainbow_sub_weights)


# -- well-known key set (for typed field assignment) --------------------------

_BOOL_KEYS = {
    "dashboard_velocity",
    "dashboard_weather",
    "dashboard_types",
    "dashboard_age",
    "dashboard_badges",
    "dashboard_recent_sessions",
    "dashboard_velocity_meter",
}

_INT_KEYS = {
    "art_frontier_since",
    "dashboard_meter_cap",
    "timeline_label_days",
    "timeline_label_df_cap_pct",
    "timeline_label_min",
    "done_section_limit",
    "art_weight_rainbow",
    "art_weight_emoji",
    "art_weight_ascii",
    "art_weight_mixed",
    "art_weight_frontier",
}

_STR_KEYS = {
    "timeline_widget",
    "timeline_scope",
    "dashboard_sessions_scope",
    "timeline_extra_stopwords",
    "art_override",
}

# Named rainbow sub-modes that map to dedicated dataclass fields.
_RAINBOW_SUB_KEYS = {
    "art_weight_rainbow_random",
    "art_weight_rainbow_letters",
    "art_weight_rainbow_halves",
    "art_weight_rainbow_gradient",
    "art_weight_rainbow_emoji",
}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def parse_config(config_path: str | None, *, repo_root: str | None = None) -> BoardConfig:
    """Parse board settings into a :class:`BoardConfig`.

    Normal rendering reads ``<repo_root>/.yoke/board.json``. Explicit
    ``config_path`` accepts JSON; key=value remains only for direct preview
    fixtures and operator-debug paths.
    """
    cfg = BoardConfig()
    source = _resolve_source(config_path, repo_root)
    if source is not None and source.is_file():
        values = _read_values(source)
        _apply_values(cfg, values)
    return cfg


def _resolve_source(config_path: str | None, repo_root: str | None) -> Path | None:
    if config_path:
        return Path(config_path).expanduser()
    if repo_root:
        return board_config_path(repo_root)
    return None


def _read_values(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return dict(payload) if isinstance(payload, Mapping) else {}
    return _read_key_value_settings(path)


def _read_key_value_settings(path: Path) -> dict[str, str]:
    """Read a ``key=value`` fixture file (operator-debug / preview path only).

    The non-JSON branch: skip blank/comment lines, split on the first ``=``,
    drop any trailing ``# inline comment``, and strip a single layer of
    surrounding quotes from the value.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = raw_value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def _apply_values(cfg: BoardConfig, values: Mapping[str, Any]) -> None:
    rainbow_sub_seen = False
    allowed = {item.name for item in fields(BoardConfig)}
    for key, value in values.items():
        if key not in allowed and not str(key).startswith("art_weight_rainbow_"):
            continue
        if key in _BOOL_KEYS:
            setattr(cfg, key, _coerce_bool(value))
        elif key in _INT_KEYS:
            _set_int(cfg, key, value)
        elif key in _STR_KEYS:
            setattr(cfg, key, str(value))
        elif key in _RAINBOW_SUB_KEYS or str(key).startswith("art_weight_rainbow_"):
            if _set_rainbow_sub_weight(cfg, key, value):
                rainbow_sub_seen = True
    if not rainbow_sub_seen:
        cfg.rainbow_sub_weights = {}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _parse_bool(str(value))


def _set_int(cfg: BoardConfig, key: str, value: Any) -> None:
    try:
        setattr(cfg, key, int(value))
    except (TypeError, ValueError):
        pass


def _set_rainbow_sub_weight(cfg: BoardConfig, key: str, value: Any) -> bool:
    try:
        int_val = int(value)
    except (TypeError, ValueError):
        return False
    if key in _RAINBOW_SUB_KEYS:
        setattr(cfg, key, int_val)
    sub_name = str(key).replace("art_weight_rainbow_", "")
    cfg.rainbow_sub_weights[sub_name] = int_val
    return True
