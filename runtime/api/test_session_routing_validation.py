"""The write boundary every ``session-routing`` writer passes through.

Read-side leniency is only safe if nothing malformed can be stored, so
these cases are the ones that must be impossible to write: a glyph the
board cannot align, a level label two levels share, a reference to a level that does not exist, and a selector that
routes two ways at once. The live document each project already stores
must keep validating, or the contract tightened past its own data.
"""

from __future__ import annotations

import pytest

from yoke_contracts.project_contract.project_keys import (
    SESSION_ROUTING_CAPABILITY,
)
from yoke_core.domain import json_helper
from yoke_core.domain.project_session_routing_defaults import (
    session_routing_defaults,
)
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)
from yoke_core.domain.session_routing_validation import (
    MAX_LEVEL_LABEL_CHARS,
    SessionRoutingSettingsError,
    validate_session_routing_settings,
)

# The document shape every project in this universe stores today. A
# tightening that refuses it would have refused the fleet.
_LIVE_SHAPED = {
    "executor_default_levels": {
        "ALTMAN": "ALTMAN",
        "DARIUS": "DARIUS",
        "MUSKY": "MUSKY",
        "claude*": "DARIUS",
        "codex*": "ALTMAN",
        "cursor*": "MUSKY",
    },
    "level_metadata": {
        "ALTMAN": {"glyph": "\U0001f453", "label": "ALTMAN"},
        "DARIUS": {"glyph": "\U0001f40e", "label": "DARIUS"},
        "MUSKY": {"glyph": "\U0001f6f8", "label": "MUSKY"},
    },
}


def _with(**overrides):
    document = json_helper.loads_text(json_helper.dumps_compact(_LIVE_SHAPED))
    document.update(overrides)
    return document


class TestAcceptedDocuments:
    def test_the_document_every_project_stores_today_validates(self):
        validate_session_routing_settings(_LIVE_SHAPED)

    def test_the_shipped_defaults_validate(self):
        validate_session_routing_settings(session_routing_defaults())

    def test_an_empty_document_validates(self):
        validate_session_routing_settings({})

    def test_unrelated_settings_are_left_alone(self):
        validate_session_routing_settings(_with(max_chain_steps=5))

    def test_a_custom_level_with_its_own_label_and_glyph_validates(self):
        validate_session_routing_settings(
            {
                "level_metadata": {"BLAH": {"label": "BLAH", "glyph": "\U0001f680"}},
                "executor_default_levels": {"claude*": "BLAH"},
            }
        )

    def test_a_label_may_differ_from_the_stored_identity(self):
        # Renaming presentation must never move the stored level identity.
        validate_session_routing_settings(
            {
                "level_metadata": {
                    "MUSKY": {"label": "ROCKETS", "glyph": "\U0001f680"}
                },
            }
        )


class TestRefusedDocuments:
    def test_an_unsafe_glyph_is_refused_and_the_field_is_named(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(level_metadata={"DARIUS": {"label": "DARIUS", "glyph": "⚠️"}})
            )
        assert caught.value.field == "level_metadata.DARIUS.glyph"
        assert "\U0001f40e" in str(caught.value)

    def test_a_lowercase_label_is_refused_with_the_uppercase_form(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(level_metadata={"DARIUS": {"label": "darius"}})
            )
        assert "'DARIUS'" in str(caught.value)

    def test_two_levels_sharing_a_label_are_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(
                    level_metadata={
                        "DARIUS": {"label": "SAME"},
                        "ALTMAN": {"label": "SAME"},
                    }
                )
            )
        assert "already used by level" in str(caught.value)

    def test_an_over_long_label_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError):
            validate_session_routing_settings(
                _with(
                    level_metadata={
                        "DARIUS": {"label": "D" * (MAX_LEVEL_LABEL_CHARS + 1)}
                    }
                )
            )

    def test_the_reserved_unresolved_identity_cannot_name_a_level(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                {"level_metadata": {"primary": {"label": "PRIMARY"}}}
            )
        assert "reserved identity" in str(caught.value)

    def test_a_harness_default_naming_a_missing_level_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                {
                    "level_metadata": {"DARIUS": {"label": "DARIUS"}},
                    "executor_default_levels": {"claude*": "NOWHERE"},
                }
            )
        assert caught.value.field == "executor_default_levels.claude*"
        assert "does not declare" in str(caught.value)

    def test_a_rule_naming_a_missing_level_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(level_rules=[{"harness": "cursor", "level": "NOWHERE"}])
            )
        assert caught.value.field == "level_rules[0].level"

    def test_a_duplicate_rule_selector_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(
                    level_rules=[
                        {"harness": "cursor", "level": "MUSKY"},
                        {"harness": "cursor", "level": "ALTMAN"},
                    ]
                )
            )
        assert "repeats a selector" in str(caught.value)


class TestWriteBoundary:
    """The capability canonicalizer is the one hook every writer shares."""

    def test_a_valid_document_canonicalizes_through_the_capability_hook(self):
        canonical = canonicalize_capability_settings(
            SESSION_ROUTING_CAPABILITY, json_helper.dumps_compact(_LIVE_SHAPED)
        )
        assert json_helper.loads_text(canonical) == _LIVE_SHAPED

    def test_an_invalid_document_is_refused_by_the_capability_hook(self):
        with pytest.raises(SessionRoutingSettingsError):
            canonicalize_capability_settings(
                SESSION_ROUTING_CAPABILITY,
                json_helper.dumps_compact(
                    _with(level_metadata={"DARIUS": {"glyph": "\U0001f44d\U0001f3fb"}})
                ),
            )

    def test_a_non_object_document_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError):
            canonicalize_capability_settings(SESSION_ROUTING_CAPABILITY, "[]")

    def test_a_settings_error_is_a_value_error_the_handler_maps(self):
        # The registered handler turns ValueError into validation_error with
        # the payload jsonpath, so this inheritance is the mapping.
        assert issubclass(SessionRoutingSettingsError, ValueError)


@pytest.mark.parametrize("key", ["lane_paths", "lane_paths_DARIUS"])
def test_removed_action_permissions_are_refused_with_recovery(key):
    with pytest.raises(SessionRoutingSettingsError) as refusal:
        validate_session_routing_settings(_with(**{key: {}}))
    assert refusal.value.field == key
    assert "lane_action_allowlists_retired" in str(refusal.value)
    assert "remove these settings keys" in str(refusal.value)


def test_level_metadata_identity_must_be_canonical():
    with pytest.raises(SessionRoutingSettingsError, match="'DARIUS'"):
        validate_session_routing_settings({"level_metadata": {"darius": {}}})


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("lane_metadata", "level_metadata"),
        ("lane_rules", "level_rules"),
        ("executor_default_lanes", "executor_default_levels"),
        ("executor_default_lane_codex", "executor_default_level_codex"),
    ],
)
def test_renamed_lane_keys_are_refused_naming_the_level_key(key, replacement):
    with pytest.raises(SessionRoutingSettingsError) as refusal:
        validate_session_routing_settings(_with(**{key: {}}))
    assert refusal.value.field == key
    assert "lane_routing_keys_renamed" in str(refusal.value)
    assert f"{key} to {replacement}" in str(refusal.value)


def test_a_rule_still_naming_a_lane_is_refused_naming_level():
    with pytest.raises(SessionRoutingSettingsError) as refusal:
        validate_session_routing_settings(
            _with(level_rules=[{"model": "gpt-*", "lane": "ALTMAN"}])
        )
    assert refusal.value.field == "level_rules[0].lane"
    assert "Rename the rule's lane key to level" in str(refusal.value)
