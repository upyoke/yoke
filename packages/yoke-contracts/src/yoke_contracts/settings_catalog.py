"""Closed, uniquely named settings across local and shared authorities."""

from __future__ import annotations

from difflib import get_close_matches
import re

from yoke_contracts.setting_spec import SettingSpec
from yoke_contracts.machine_config.settings_keys import MACHINE_SETTING_KEYS
from yoke_contracts.project_contract.project_keys import RECOGNIZED_PROJECT_KEYS
from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_contracts.levels import default_levels
from yoke_contracts.session_control.plan_limits import (
    CURSOR_MODELS_SCOPE,
    CURSOR_OTHER_MODELS_SCOPE,
)

UNIVERSE_SETTING_KEYS = {
    "levels": SettingSpec(
        [level.payload() for level in default_levels()],
        list,
        "ordered execution levels; unset follows future shipped defaults",
    ),
    "cursor_quota_order": SettingSpec(
        [CURSOR_MODELS_SCOPE, CURSOR_OTHER_MODELS_SCOPE],
        list,
        "consumption order of Cursor monthly quota pools",
    ),
}
SCOPES = {
    "machine": MACHINE_SETTING_KEYS,
    "project": RECOGNIZED_PROJECT_KEYS,
    "org": FLEET_KEY_SPECS,
    "universe": UNIVERSE_SETTING_KEYS,
}


def build_catalog(scopes=SCOPES):
    catalog = {}
    for scope, specs in scopes.items():
        for key, spec in specs.items():
            if key in catalog:
                raise ValueError(f"setting_key_duplicate: {key}")
            if re.search(
                r"(?:password|secret|token|credential|private_key|api_key)", key, re.I
            ):
                raise ValueError(f"setting_key_sensitive: {key}")
            catalog[key] = (scope, spec)
    return catalog


CATALOG = build_catalog()


def resolve_setting(key):
    if key not in CATALOG:
        closest = get_close_matches(key, CATALOG, n=1)
        hint = f" Did you mean {closest[0]}?" if closest else ""
        raise ValueError(
            f"setting_key_unknown: {key}.{hint} Recovery: yoke settings list"
        )
    return CATALOG[key]
