"""Tests for the substrate failure taxonomy + classifier helper.

Separate test module to keep ``test_sessions_handler_outcome.py`` under the
300-line design target while the taxonomy stays close to the constants it
routes to in ``sessions_handler_outcome.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.sessions_handler_outcome import (
    OUTCOME_BLOCKED,
    OUTCOME_RECOVERABLE_SUBSTRATE,
    SUBSTRATE_FAILURE_TAXONOMY,
    classify_substrate_failure,
    is_terminal_outcome,
)


class TestSubstrateFailureTaxonomy:
    def test_taxonomy_includes_starter_classes(self):
        expected = {
            "dirty-tracked-main",
            "unbound-worktree",
            "path-claim-overlap-incompatible",
            "lease-conflict",
        }
        assert expected <= set(SUBSTRATE_FAILURE_TAXONOMY)

    def test_recoverable_starter_classes_route_to_recoverable_substrate(self):
        for key in ("dirty-tracked-main", "unbound-worktree", "lease-conflict"):
            assert SUBSTRATE_FAILURE_TAXONOMY[key] == OUTCOME_RECOVERABLE_SUBSTRATE

    def test_overlap_incompatible_routes_to_blocked(self):
        assert (
            SUBSTRATE_FAILURE_TAXONOMY["path-claim-overlap-incompatible"]
            == OUTCOME_BLOCKED
        )


class TestClassifySubstrateFailure:
    @pytest.mark.parametrize(
        "failure_class,expected",
        [
            ("dirty-tracked-main", OUTCOME_RECOVERABLE_SUBSTRATE),
            ("unbound-worktree", OUTCOME_RECOVERABLE_SUBSTRATE),
            ("path-claim-overlap-incompatible", OUTCOME_BLOCKED),
            ("lease-conflict", OUTCOME_RECOVERABLE_SUBSTRATE),
        ],
    )
    def test_known_class_returns_mapped_outcome(self, failure_class, expected):
        assert classify_substrate_failure(failure_class) == expected

    def test_unknown_class_defaults_to_blocked(self):
        assert (
            classify_substrate_failure("never-seen-before-class") == OUTCOME_BLOCKED
        )

    def test_blocked_taxonomy_class_is_terminal(self):
        outcome = classify_substrate_failure("path-claim-overlap-incompatible")
        assert is_terminal_outcome(outcome) is True

    def test_empty_string_defaults_to_blocked(self):
        assert classify_substrate_failure("") == OUTCOME_BLOCKED

    def test_none_defaults_to_blocked(self):
        assert classify_substrate_failure(None) == OUTCOME_BLOCKED
