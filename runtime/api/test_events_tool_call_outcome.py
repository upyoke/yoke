"""Unit tests for ``classify_tool_call_outcome`` truth table.

These tests exercise the classifier in isolation — no DB, no observe
pipeline, no hook payloads. Each test asserts on one branch of the
truth table in :func:`yoke_core.domain.events_tool_call_outcome.classify_tool_call_outcome`
using the exported ``OUTCOME_*`` constants (never string literals).
"""

from __future__ import annotations

from yoke_core.domain.events_tool_call_outcome import (
    OUTCOME_COMPLETED,
    OUTCOME_DENIED,
    OUTCOME_FAILED,
    OUTCOME_INTERRUPTED,
    OUTCOME_STRUCTURED_EXIT,
    OUTCOME_SUPPRESSION_ATTEMPTED,
    OUTCOME_WARN,
    OUTCOMES,
    classify_tool_call_outcome,
)
from yoke_core.domain.observe_parsing import EventRecord


class TestOutcomesFrozenset:
    """The ``OUTCOMES`` set carries the five classifier outcomes plus the two
    event-class-conditional ``HarnessToolCallDenied`` outcomes."""

    def test_outcomes_contains_seven_members(self):
        assert len(OUTCOMES) == 7

    def test_outcomes_membership(self):
        assert OUTCOME_COMPLETED in OUTCOMES
        assert OUTCOME_FAILED in OUTCOMES
        assert OUTCOME_DENIED in OUTCOMES
        assert OUTCOME_INTERRUPTED in OUTCOMES
        assert OUTCOME_STRUCTURED_EXIT in OUTCOMES

    def test_outcomes_includes_lint_guardrail_values(self):
        assert OUTCOME_WARN == "warn"
        assert OUTCOME_SUPPRESSION_ATTEMPTED == "suppression_attempted"
        assert OUTCOME_WARN in OUTCOMES
        assert OUTCOME_SUPPRESSION_ATTEMPTED in OUTCOMES

    def test_outcomes_is_immutable_frozenset(self):
        assert isinstance(OUTCOMES, frozenset)


class TestClassifyDenied:
    """Branch 1: permission decision + is_failure -> denied."""

    def test_permission_denied_returns_denied(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            exit_code=1,
            has_permission_decision=True,
        )
        outcome, exit_code = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_DENIED
        assert exit_code == 1
        assert outcome in OUTCOMES

    def test_permission_decision_without_failure_does_not_deny(self):
        # has_permission_decision alone (without is_failure) is an
        # approval that succeeded — not a denial.
        rec = EventRecord(
            tool_name="Bash",
            is_failure=False,
            exit_code=0,
            has_permission_decision=True,
        )
        outcome, _ = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_COMPLETED


class TestClassifyStructuredExit:
    """Branch 2: structured_exit in anomalies -> structured_exit."""

    def test_structured_exit_anomaly_returns_structured_exit(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            exit_code=None,
            anomalies=["structured_exit"],
        )
        outcome, exit_code = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_STRUCTURED_EXIT
        assert exit_code is None
        assert outcome in OUTCOMES

    def test_structured_exit_wins_over_plain_failure(self):
        # structured_exit branch must fire before the plain failed branch.
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            exit_code=7,
            anomalies=["structured_exit", "nonzero_exit"],
        )
        outcome, _ = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_STRUCTURED_EXIT


class TestClassifyFailedFromIsFailureFlag:
    """Branch 3: is_failure=True (and no denial/structured_exit) -> failed."""

    def test_is_failure_returns_failed(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            exit_code=2,
        )
        outcome, exit_code = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_FAILED
        assert exit_code == 2
        assert outcome in OUTCOMES

    def test_is_failure_with_no_exit_code_preserves_none(self):
        rec = EventRecord(
            tool_name="Write",
            is_failure=True,
            exit_code=None,
        )
        outcome, exit_code = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_FAILED
        assert exit_code is None


class TestClassifyFailedFromNonzeroExit:
    """Branch 4: exit_code>0 with is_failure=False -> failed (defense in depth)."""

    def test_nonzero_exit_without_is_failure_still_failed(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=False,
            exit_code=127,
        )
        outcome, exit_code = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_FAILED
        assert exit_code == 127
        assert outcome in OUTCOMES


class TestClassifyCompleted:
    """Branch 5: everything else -> completed."""

    def test_clean_zero_exit_returns_completed(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=False,
            exit_code=0,
        )
        outcome, exit_code = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_COMPLETED
        assert exit_code == 0
        assert outcome in OUTCOMES

    def test_completed_with_none_exit_normalizes_to_zero(self):
        # AC-2 last line: ``(OUTCOME_COMPLETED, rec.exit_code or 0)``.
        # Non-Bash tools (Write/Read/Edit) leave exit_code=None on
        # success; the classifier records exit_code=0 for them.
        rec = EventRecord(
            tool_name="Write",
            is_failure=False,
            exit_code=None,
        )
        outcome, exit_code = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_COMPLETED
        assert exit_code == 0

    def test_completed_without_anomalies(self):
        rec = EventRecord(tool_name="Read", is_failure=False)
        outcome, _ = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_COMPLETED


class TestTruthTableOrdering:
    """The five branches must be tried in the documented order."""

    def test_denied_beats_structured_exit(self):
        # If both a permission decision and structured_exit anomaly fire
        # (unusual but possible: a permission denial path that also
        # surfaces approval-gate text), the explicit denial wins.
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            exit_code=1,
            has_permission_decision=True,
            anomalies=["structured_exit"],
        )
        outcome, _ = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_DENIED

    def test_is_failure_beats_defense_in_depth_exit_branch(self):
        # When both branches 3 and 4 would match, branch 3 fires — and
        # both produce OUTCOME_FAILED, so the practical outcome is the
        # same. Lock in the consistency anyway.
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            exit_code=5,
        )
        outcome, _ = classify_tool_call_outcome(rec)
        assert outcome == OUTCOME_FAILED


class TestEveryOutcomeRoundTripsThroughOutcomes:
    """``outcome in OUTCOMES`` must hold for every classifier output."""

    def test_all_emitted_outcomes_are_members(self):
        recs = [
            EventRecord(is_failure=False, exit_code=0),  # completed
            EventRecord(is_failure=True, exit_code=2),  # failed
            EventRecord(is_failure=False, exit_code=7),  # failed (defense)
            EventRecord(
                is_failure=True,
                exit_code=1,
                has_permission_decision=True,
            ),  # denied
            EventRecord(
                is_failure=True,
                exit_code=None,
                anomalies=["structured_exit"],
            ),  # structured_exit
        ]
        for rec in recs:
            outcome, _ = classify_tool_call_outcome(rec)
            assert outcome in OUTCOMES, (
                f"outcome {outcome!r} not in OUTCOMES — classifier "
                f"violated round-trip invariant"
            )


class TestNamedLintEmitterLiterals:
    """AC-2: every named ``HarnessToolCallDenied`` emitter's outcome literal
    is a member of OUTCOMES. The emitter modules in the inventory below
    pass either a string literal or a local variable bound to one of
    these literals to ``emit_denial_event(outcome=...)``."""

    # (module path, set of literals that module may pass as outcome)
    # Inventory drawn from the spec's Refinement Notes 2026-05-20
    # HarnessToolCallDenied emitter inventory.
    NAMED_EMITTER_LITERALS = {
        "yoke_core.domain.lint_destructive_git": {
            "suppression_attempted",
            "denied",
        },
        "yoke_core.domain.lint_long_command_polling_decide": {
            "warn",
            "suppression_attempted",
        },
        "yoke_core.domain.lint_python_runtime_import_in_tmp": {
            "suppression_attempted",
        },
        "yoke_core.domain.lint_shell_quoted_function_payload": {
            "suppression_attempted",
            "warn",
        },
        "yoke_core.domain.lint_structured_field_transform_shell": {
            "suppression_attempted",
        },
        "yoke_core.domain.lint_subagent_background_decide": {
            "warn",
            "suppression_attempted",
        },
        "yoke_core.domain.lint_workspace_cwd_match": {
            "suppression_attempted",
            "denied",
        },
    }

    def test_every_named_literal_is_in_outcomes(self):
        for module_path, literals in self.NAMED_EMITTER_LITERALS.items():
            for literal in literals:
                assert literal in OUTCOMES, (
                    f"{module_path} emits outcome={literal!r} which is "
                    f"not a member of OUTCOMES={sorted(OUTCOMES)}"
                )


class TestFailedOutcomesExcludesLintGuardrailValues:
    """AC-3: ``--failed-only`` must not sweep ``warn`` or
    ``suppression_attempted`` rows. They are audit signals, not denials.
    ``FAILED_OUTCOMES`` is imported inside each test to avoid the
    ``events_audit_presets`` → ``events_crud`` → ``events_queries``
    circular-import chain that triggers when this module is loaded in
    isolation."""

    def test_warn_not_in_failed_outcomes(self):
        from yoke_core.domain.events_audit_presets import FAILED_OUTCOMES

        assert OUTCOME_WARN not in FAILED_OUTCOMES

    def test_suppression_attempted_not_in_failed_outcomes(self):
        from yoke_core.domain.events_audit_presets import FAILED_OUTCOMES

        assert OUTCOME_SUPPRESSION_ATTEMPTED not in FAILED_OUTCOMES

    def test_failed_outcomes_set_is_stable(self):
        # Defense in depth: lock in the closed set ``--failed-only`` matches.
        from yoke_core.domain.events_audit_presets import FAILED_OUTCOMES

        assert set(FAILED_OUTCOMES) == {
            "failed",
            "denied",
            "interrupted",
            "timeout",
        }
