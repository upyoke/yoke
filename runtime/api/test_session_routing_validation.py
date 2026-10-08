"""The write boundary every ``session-routing`` writer passes through.

The document is a project's override of the universe execution levels and
carries one key, ``levels``. Everything the readers no longer consult —
declared metadata, selector rules, harness defaults, and the older lane and
process-offer keys — is refused by name with the command that writes a
valid override.
"""

from __future__ import annotations

import pytest

from yoke_contracts.levels import default_levels, levels_payload
from yoke_contracts.project_contract.project_keys import (
    SESSION_ROUTING_CAPABILITY,
)
from yoke_core.domain import json_helper
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)
from yoke_core.domain.session_routing_validation import (
    SessionRoutingSettingsError,
    validate_session_routing_settings,
)

OVERRIDE = {"levels": levels_payload(default_levels()[:2])}


def _refusal(document) -> SessionRoutingSettingsError:
    with pytest.raises(SessionRoutingSettingsError) as caught:
        validate_session_routing_settings(document)
    return caught.value


def test_a_levels_override_validates():
    validate_session_routing_settings(OVERRIDE)


def test_an_override_must_carry_levels():
    error = _refusal({})
    assert error.field == "levels"
    assert "session_routing_levels_missing" in str(error)


def test_an_invalid_level_is_refused_at_its_path():
    document = json_helper.loads_text(json_helper.dumps_compact(OVERRIDE))
    document["levels"][0]["options"][0]["model"] = "claude-*"
    error = _refusal(document)
    assert error.field == "levels[0].options[0].model"
    assert "level_option_model_not_launchable" in str(error)


@pytest.mark.parametrize(
    "key",
    [
        "level_metadata",
        "level_rules",
        "executor_default_levels",
        "executor_default_level_codex",
        "lane_metadata",
        "executor_default_lane_codex",
    ],
)
def test_retired_level_routing_keys_are_refused_with_the_override_recipe(key):
    error = _refusal({**OVERRIDE, key: {}})
    assert error.field == key
    assert "level_routing_keys_retired" in str(error)
    assert "yoke projects capability-settings set" in str(error)


@pytest.mark.parametrize(
    ("key", "code"),
    [
        ("lane_paths", "lane_action_allowlists_retired"),
        ("process_offers", "process_offer_policy_retired"),
    ],
)
def test_older_retired_keys_keep_their_named_refusal(key, code):
    error = _refusal({**OVERRIDE, key: {}})
    assert error.field == key
    assert code in str(error)


def test_an_unknown_key_is_refused():
    error = _refusal({**OVERRIDE, "max_chain_steps": 3})
    assert error.field == "max_chain_steps"
    assert "session_routing_key_unknown" in str(error)


class TestWriteBoundary:
    """The capability canonicalizer is the one hook every writer shares."""

    def test_a_valid_override_canonicalizes_through_the_capability_hook(self):
        canonical = canonicalize_capability_settings(
            SESSION_ROUTING_CAPABILITY, json_helper.dumps_compact(OVERRIDE)
        )
        assert json_helper.loads_text(canonical) == OVERRIDE

    def test_an_invalid_document_is_refused_by_the_capability_hook(self):
        with pytest.raises(SessionRoutingSettingsError):
            canonicalize_capability_settings(
                SESSION_ROUTING_CAPABILITY,
                json_helper.dumps_compact({"level_metadata": {}}),
            )

    def test_a_non_object_document_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError):
            canonicalize_capability_settings(SESSION_ROUTING_CAPABILITY, "[]")

    def test_a_settings_error_is_a_value_error_the_handler_maps(self):
        # The registered handler turns ValueError into validation_error with
        # the payload jsonpath, so this inheritance is the mapping.
        assert issubclass(SessionRoutingSettingsError, ValueError)
