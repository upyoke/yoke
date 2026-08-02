"""Tests for the recognized machine-local settings registry."""

from __future__ import annotations

from yoke_contracts.machine_config.settings_keys import (
    MACHINE_SETTING_KEYS,
    MACHINE_SETTING_PREFIXES,
    db_owned_capability_for,
    db_owned_settings,
    is_recognized,
    machine_setting_default,
    unrecognized_settings,
)
from yoke_contracts.project_contract.project_keys import (
    DB_PROJECT_POLICY_KEYS,
    LOCAL_PROJECT_KEYS,
    PROJECT_POLICY_CAPABILITY,
    RECOGNIZED_PROJECT_KEYS,
    SESSION_ROUTING_CAPABILITY,
)


def test_every_entry_carries_a_default_and_a_meaning() -> None:
    for key, entry in MACHINE_SETTING_KEYS.items():
        default, meaning = entry
        assert isinstance(default, str), key
        assert meaning.strip(), key


def test_machine_keys_do_not_shadow_db_owned_project_policy() -> None:
    for key in DB_PROJECT_POLICY_KEYS:
        assert key not in MACHINE_SETTING_KEYS, key


def test_local_project_keys_resolve_their_project_default() -> None:
    for key in LOCAL_PROJECT_KEYS:
        assert is_recognized(key)
        assert machine_setting_default(key) == RECOGNIZED_PROJECT_KEYS[key][0]


def test_db_owned_keys_name_their_owning_capability() -> None:
    assert db_owned_capability_for("wip_cap") == PROJECT_POLICY_CAPABILITY
    assert db_owned_capability_for("base_branch") == PROJECT_POLICY_CAPABILITY
    for key in (
        "lane_paths_altman",
        "executor_default_lane_codex*",
        "do_process_offer_feed",
    ):
        assert db_owned_capability_for(key) == SESSION_ROUTING_CAPABILITY


def test_machine_owned_keys_are_not_db_owned() -> None:
    for key in MACHINE_SETTING_KEYS:
        assert db_owned_capability_for(key) is None, key


def test_prefix_families_are_recognized() -> None:
    for prefix in MACHINE_SETTING_PREFIXES:
        assert is_recognized(f"{prefix}some_check_cutoff")
    assert not is_recognized("invented_key")


def test_db_owned_settings_reports_key_and_capability() -> None:
    found = db_owned_settings(
        {"wip_cap": 30, "lane_paths_altman": "refine", "max_chain_steps": 3},
    )
    assert found == (
        ("lane_paths_altman", SESSION_ROUTING_CAPABILITY),
        ("wip_cap", PROJECT_POLICY_CAPABILITY),
    )


def test_unrecognized_settings_excludes_db_owned_twins() -> None:
    settings = {
        "max_chain_steps": 3,
        "hc_premature_done_min_item_id": 1473,
        "wip_cap": 30,
        "bloat_epic_dirs": 60,
    }
    assert unrecognized_settings(settings) == ("bloat_epic_dirs",)
