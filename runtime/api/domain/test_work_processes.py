"""Tests for the recurring work-claim process registry.

Covers AC-2 (STRATEGIZE + FEED share ``strategy-control-plane:<project>``
and conflict on the same project) and the DOCTOR process claim. The
process claim is a pure process lock — strategy doc/file enumeration
lives in :mod:`yoke_core.domain.strategy_docs`, and rendered-view
commit authorization is the matches-the-master rule in
:mod:`yoke_core.domain.lint_main_commit_process_claims`.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.work_processes import (
    PROCESS_DOCTOR,
    PROCESS_FEED,
    PROCESS_REGISTRY,
    PROCESS_STRATEGIZE,
    UnknownProcessError,
    action_kind_to_process_key,
    conflict_group_for,
    is_known_process,
    list_processes,
)


class TestProcessRegistry:

    def test_opening_canon_lists_strategize_and_feed(self):
        keys = set(list_processes())
        assert PROCESS_STRATEGIZE in keys
        assert PROCESS_FEED in keys
        assert PROCESS_DOCTOR in keys

    def test_is_known_process_recognises_canon(self):
        assert is_known_process(PROCESS_STRATEGIZE)
        assert is_known_process(PROCESS_FEED)
        assert is_known_process(PROCESS_DOCTOR)
        assert not is_known_process("BOGUS_PROCESS")

    def test_unknown_process_lookup_raises(self):
        with pytest.raises(UnknownProcessError):
            conflict_group_for("BOGUS_PROCESS", "yoke")


class TestConflictGroupSemantics:
    """AC-2: STRATEGIZE and FEED share strategy-control-plane:<project>."""

    def test_strategize_and_feed_share_group_on_same_project(self):
        a = conflict_group_for(PROCESS_STRATEGIZE, "yoke")
        b = conflict_group_for(PROCESS_FEED, "yoke")
        assert a == b == "strategy-control-plane:yoke"

    def test_distinct_projects_get_distinct_groups(self):
        yoke = conflict_group_for(PROCESS_STRATEGIZE, "yoke")
        buzz = conflict_group_for(PROCESS_STRATEGIZE, "buzz")
        assert yoke != buzz
        assert "buzz" in buzz

    def test_doctor_uses_own_project_scoped_group(self):
        assert conflict_group_for(PROCESS_DOCTOR, "yoke") == "doctor:yoke"
        assert conflict_group_for(PROCESS_DOCTOR, "yoke") != conflict_group_for(
            PROCESS_STRATEGIZE, "yoke"
        )

    def test_empty_project_rejected(self):
        with pytest.raises(ValueError):
            conflict_group_for(PROCESS_STRATEGIZE, "")
        with pytest.raises(ValueError):
            conflict_group_for(PROCESS_STRATEGIZE, "   ")


class TestRegistryShape:
    """Defensive: registry shape stays parsable for downstream callers."""

    def test_registry_keys_are_screaming_snake_case(self):
        for key in PROCESS_REGISTRY:
            assert key.isupper(), f"process key {key!r} must be uppercase"
            assert key.replace("_", "").isalnum(), (
                f"process key {key!r} must be alphanumeric / underscore"
            )

    def test_registry_entries_have_required_keys(self):
        required = {"conflict_group_template"}
        for key, spec in PROCESS_REGISTRY.items():
            missing = required - set(spec.keys())
            assert not missing, (
                f"process {key!r} missing registry keys {sorted(missing)}"
            )

    def test_template_supports_project_substitution(self):
        for key, spec in PROCESS_REGISTRY.items():
            template = str(spec["conflict_group_template"])
            assert "{project}" in template, (
                f"process {key!r} conflict_group_template missing {{project}} placeholder"
            )


class TestActionKindToProcessKey:
    """AC-17 / AC-23 / AC-43: bridge ActionKind value -> registered process key."""

    def test_strategize_action_value_maps_to_strategize_process(self):
        assert action_kind_to_process_key("strategize") == PROCESS_STRATEGIZE

    def test_feed_action_value_maps_to_feed_process(self):
        assert action_kind_to_process_key("feed") == PROCESS_FEED

    def test_non_process_actions_return_none(self):
        # CHARGE / RESUME / WAIT / ESCALATE flow through the gate untouched.
        assert action_kind_to_process_key("charge") is None
        assert action_kind_to_process_key("resume") is None
        assert action_kind_to_process_key("wait") is None
        assert action_kind_to_process_key("escalate") is None

    def test_empty_or_none_returns_none(self):
        assert action_kind_to_process_key("") is None
        # ``None`` itself is not a typed input, but the helper guards
        # against a stringified empty.
        assert action_kind_to_process_key("   ") is None

    def test_case_insensitive(self):
        assert action_kind_to_process_key("STRATEGIZE") == PROCESS_STRATEGIZE
        assert action_kind_to_process_key("Strategize") == PROCESS_STRATEGIZE
        assert action_kind_to_process_key("FEED") == PROCESS_FEED

    def test_doctor_is_not_yet_a_decision_action(self):
        # ``DOCTOR`` is a registered process key (see PROCESS_REGISTRY) but
        # ``decide_next_action`` does not currently produce a DOCTOR
        # ActionKind. The mapping intentionally omits it; the entry is
        # added once the decision engine starts surfacing DOCTOR.
        assert action_kind_to_process_key("doctor") is None
