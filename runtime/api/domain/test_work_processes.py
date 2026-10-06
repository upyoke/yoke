"""Tests for the recurring work-claim process registry.

STRATEGIZE + FEED share ``strategy-control-plane:<project>``
and conflict on the same project; the DOCTOR process claim is covered too. The
process claim is a pure process lock — strategy doc/file enumeration
lives in :mod:`yoke_core.domain.strategy_docs`.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.work_processes import (
    PROCESS_DOCTOR,
    PROCESS_FEED,
    PROCESS_REGISTRY,
    PROCESS_STRATEGIZE,
    UnknownProcessError,
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
    """STRATEGIZE and FEED share strategy-control-plane:<project>."""

    def test_strategize_and_feed_share_group_on_same_project(self):
        a = conflict_group_for(PROCESS_STRATEGIZE, "yoke")
        b = conflict_group_for(PROCESS_FEED, "yoke")
        assert a == b == "strategy-control-plane:yoke"

    def test_distinct_projects_get_distinct_groups(self):
        yoke = conflict_group_for(PROCESS_STRATEGIZE, "yoke")
        externalwebapp = conflict_group_for(PROCESS_STRATEGIZE, "externalwebapp")
        assert yoke != externalwebapp
        assert "externalwebapp" in externalwebapp

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
