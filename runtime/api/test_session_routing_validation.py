"""The write boundary every ``session-routing`` writer passes through.

Read-side leniency is only safe if nothing malformed can be stored, so
these cases are the ones that must be impossible to write: a glyph the
board cannot align, a lane label two lanes share, an action nothing
dispatches, a reference to a lane that does not exist, and a selector that
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
    MAX_LANE_LABEL_CHARS,
    SessionRoutingSettingsError,
    validate_session_routing_settings,
)

# The document shape every project in this universe stores today. A
# tightening that refuses it would have refused the fleet.
_LIVE_SHAPED = {
    "executor_default_lanes": {
        "ALTMAN": "ALTMAN",
        "DARIUS": "DARIUS",
        "MUSKY": "MUSKY",
        "claude*": "DARIUS",
        "codex*": "ALTMAN",
        "cursor*": "MUSKY",
    },
    "lane_metadata": {
        "ALTMAN": {"glyph": "\U0001f453", "label": "ALTMAN"},
        "DARIUS": {"glyph": "\U0001f40e", "label": "DARIUS"},
        "MUSKY": {"glyph": "\U0001f6f8", "label": "MUSKY"},
    },
    "lane_paths": {
        "ALTMAN": ["refine", "polish", "usher", "dash"],
        "DARIUS": ["shepherd", "dash", "steer"],
        "MUSKY": ["dash"],
    },
    "process_offers": {"default": False, "doctor": False},
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

    def test_a_custom_lane_with_its_own_label_and_glyph_validates(self):
        validate_session_routing_settings(
            {
                "lane_metadata": {"BLAH": {"label": "BLAH", "glyph": "\U0001f680"}},
                "lane_paths": {"BLAH": ["dash"]},
                "executor_default_lanes": {"claude*": "BLAH"},
            }
        )

    def test_a_label_may_differ_from_the_stored_identity(self):
        # Renaming presentation must never move the stored lane identity.
        validate_session_routing_settings(
            {
                "lane_metadata": {"MUSKY": {"label": "ROCKETS", "glyph": "\U0001f680"}},
                "lane_paths": {"MUSKY": ["dash"]},
            }
        )

    def test_the_flat_allowlist_grammar_is_validated_too(self):
        validate_session_routing_settings(
            {"lane_paths_DARIUS": "dash,polish"}
        )


class TestRefusedDocuments:
    def test_an_unsafe_glyph_is_refused_and_the_field_is_named(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(lane_metadata={"DARIUS": {"label": "DARIUS", "glyph": "⚠️"}})
            )
        assert caught.value.field == "lane_metadata.DARIUS.glyph"
        assert "\U0001f40e" in str(caught.value)

    def test_a_lowercase_label_is_refused_with_the_uppercase_form(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(lane_metadata={"DARIUS": {"label": "darius"}})
            )
        assert "'DARIUS'" in str(caught.value)

    def test_two_lanes_sharing_a_label_are_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(
                    lane_metadata={
                        "DARIUS": {"label": "SAME"},
                        "ALTMAN": {"label": "SAME"},
                    }
                )
            )
        assert "already used by lane" in str(caught.value)

    def test_an_over_long_label_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError):
            validate_session_routing_settings(
                _with(
                    lane_metadata={
                        "DARIUS": {"label": "D" * (MAX_LANE_LABEL_CHARS + 1)}
                    }
                )
            )

    def test_the_reserved_unresolved_identity_cannot_name_a_lane(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                {"lane_metadata": {"primary": {"label": "PRIMARY"}}}
            )
        assert "reserved identity" in str(caught.value)

    def test_an_action_nothing_dispatches_is_refused_and_lists_the_catalog(
        self,
    ):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(lane_paths={"DARIUS": ["dash", "teleport"]})
            )
        assert caught.value.field == "lane_paths.DARIUS"
        assert "teleport" in str(caught.value)
        assert "shepherd" in str(caught.value)

    def test_an_empty_allowlist_is_accepted_as_a_lane_that_runs_nothing(self):
        # It is a real configuration, not a typo for "everything".
        validate_session_routing_settings(_with(lane_paths={"DARIUS": []}))

    def test_a_harness_default_naming_a_missing_lane_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                {
                    "lane_metadata": {"DARIUS": {"label": "DARIUS"}},
                    "executor_default_lanes": {"claude*": "NOWHERE"},
                }
            )
        assert caught.value.field == "executor_default_lanes.claude*"
        assert "does not declare" in str(caught.value)

    def test_a_rule_naming_a_missing_lane_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(lane_rules=[{"harness": "cursor", "lane": "NOWHERE"}])
            )
        assert caught.value.field == "lane_rules[0].lane"

    def test_a_duplicate_rule_selector_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                _with(
                    lane_rules=[
                        {"harness": "cursor", "lane": "MUSKY"},
                        {"harness": "cursor", "lane": "ALTMAN"},
                    ]
                )
            )
        assert "repeats a selector" in str(caught.value)

    def test_a_lane_identity_that_routing_would_rename_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError) as caught:
            validate_session_routing_settings(
                {"lane_paths": {"darius": ["dash"]}}
            )
        assert "'DARIUS'" in str(caught.value)


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
                    _with(lane_metadata={"DARIUS": {"glyph": "\U0001f44d\U0001f3fb"}})
                ),
            )

    def test_a_non_object_document_is_refused(self):
        with pytest.raises(SessionRoutingSettingsError):
            canonicalize_capability_settings(SESSION_ROUTING_CAPABILITY, "[]")

    def test_a_settings_error_is_a_value_error_the_handler_maps(self):
        # The registered handler turns ValueError into validation_error with
        # the payload jsonpath, so this inheritance is the mapping.
        assert issubclass(SessionRoutingSettingsError, ValueError)
