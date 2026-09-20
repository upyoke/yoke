"""The post_deploy done refusal states the condition on every exit it names.

``POST_DEPLOY_RECOVERY`` names three ways out of an unsatisfied post_deploy
obligation, and they are not equally available. The supersede exit is the
narrow one: the refusal is printed while the completion run is already
``succeeded``, and
:data:`qa_requirement_deployment_run_create.CLOSED_RUN_STATUSES` refuses a new
run-bound case on a finished run, so that exit is open only to a reader who
already authored the corrected case. A reader told to supersede, with no way
to know it is impossible for them, is being handed a dead end.

The fix is prose: every exit carries its condition, and all three print every
time. The tempting alternative -- read the case state and print only the
reachable exits -- is what these tests exist to prevent, for two reasons. A
refusal that tailors itself recreates the ambiguity it meant to remove, since
a missing exit could mean "ruled out for you" or "this surface chose not to
say"; absence-by-omission is the failure that cost an operator-authorized
waiver. And a read on the refusal path is paid on every refusal for a benefit
on only some, which is the wrong cost shape for a path that only runs when
something has already gone wrong.

NOTE for whoever reads the query-count assertions below and takes them for a
performance test: they are not one. They are the structural half of the
stance, and each of the three catches something the others miss. Text
equality across two deliveries catches a refusal that prints different exits
for different case states. Query-count equality across those same two catches
a read taken only in one shape, even if someone keeps the wording identical.
Neither catches a read taken on every post_deploy refusal alike, since both
deliveries would pay it -- so the last assertion renders the same row in a
phase that appends no recovery at all and requires printing the exits to cost
exactly zero queries.

Every comparison is relative on purpose rather than pinned to a number.
``done_gate_refusal_errors`` legitimately issues one
``requirement_awaits_human_review`` query per blocking row; holding the row
shape identical across all three renders keeps that query from making any of
them brittle.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.fixtures.deployment_admitted_case_fixture import (
    deliver_with_failing_admitted_copy,
    succeed_run,
)
from yoke_core.domain.deployment_qa_source_obligation import POST_DEPLOY_RECOVERY
from yoke_core.domain.qa_done_gate_refusal import done_gate_refusal_errors

# Each exit as a reader meets it in the text, paired with the action that
# identifies it. Matching on the action rather than on a whole sentence lets
# the prose be reworded freely; what may not change is that the sentence
# carrying the action also carries a condition.
EXIT_ACTIONS = (
    "deliver the item",
    "yoke qa requirement supersede",
    "waive the requirement",
)
CONDITION_MARKERS = ("if ", "unless ", "when ")


class _CountingConn:
    """Pass every call through, counting the queries the wrapped code runs."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.queries = 0

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        self.queries += 1
        return self._conn.execute(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _post_deploy_row(requirement_id: int) -> dict[str, Any]:
    """One blocking post_deploy row shaped as the done gate hands it over."""
    return {
        "id": requirement_id,
        "qa_kind": "command",
        "qa_phase": "post_deploy",
        "passed": False,
    }


RECOVERY_OPENING = "A post_deploy obligation is satisfied"


def _verification_row(requirement_id: int) -> dict[str, Any]:
    """The same row in a phase that appends no recovery, as the baseline."""
    return dict(_post_deploy_row(requirement_id), qa_phase="verification")


def _recovery_line(errors: list[str]) -> str:
    matches = [line for line in errors if RECOVERY_OPENING in line]
    assert len(matches) == 1, f"expected one recovery line, got {len(matches)}"
    line = matches[0].strip()
    assert line == POST_DEPLOY_RECOVERY, (
        "the refusal rendered something other than the recovery constant "
        "verbatim, so it is editing the exits before printing them"
    )
    return line


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in text.split(". ") if part.strip()]


def test_rendered_done_refusal_states_a_condition_on_every_exit(test_db) -> None:
    """Each named exit sits in a sentence that says when it applies."""
    item_id = 2350
    run_id = "run-recovery-conditions"
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, _broken_id, _corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=run_id, corrected=False
    )
    succeed_run(test_db, run_id)

    errors = done_gate_refusal_errors(
        test_db, [_post_deploy_row(intake_id)], name="YOKE item"
    )
    recovery = _recovery_line(errors).lower()
    sentences = _sentences(recovery)

    for action in EXIT_ACTIONS:
        assert action in recovery, f"recovery no longer names the {action!r} exit"
        carrying = [sentence for sentence in sentences if action in sentence]
        assert carrying, f"{action!r} is not inside any sentence"
        assert any(
            marker in sentence
            for sentence in carrying
            for marker in CONDITION_MARKERS
        ), (
            f"the {action!r} exit is named with no condition attached; a reader "
            "cannot tell whether it is available to them"
        )


def test_refusal_does_not_read_per_case_to_decide_which_exits_to_print(
    test_db,
) -> None:
    """Two deliveries differing only in admitted-copy state render identically.

    One authored a corrected sibling that passed, the other did not -- the
    exact state a tailored refusal would consult to decide whether to offer
    the supersede exit. Same text and same query count means it did not ask.
    """
    _insert_dash(test_db, item_id=2351, status="release")
    _insert_dash(test_db, item_id=2352, status="release")
    with_corrected, _, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=2351, run_id="run-recovery-corrected", corrected=True
    )
    without_corrected, _, absent_id = deliver_with_failing_admitted_copy(
        test_db, item_id=2352, run_id="run-recovery-uncorrected", corrected=False
    )
    succeed_run(test_db, "run-recovery-corrected")
    succeed_run(test_db, "run-recovery-uncorrected")
    # The deliveries really do differ in the state a conditional read would ask
    # about, so identical output below is evidence rather than coincidence.
    assert corrected_id and not absent_id

    rendered = []
    for requirement_id in (with_corrected, without_corrected):
        counting = _CountingConn(test_db)
        errors = done_gate_refusal_errors(
            counting, [_post_deploy_row(requirement_id)], name="YOKE item"
        )
        rendered.append((_recovery_line(errors), counting.queries))

    (corrected_text, corrected_queries), (absent_text, absent_queries) = rendered
    assert corrected_text == absent_text, (
        "the recovery text varies with admitted-copy state, so the refusal is "
        "tailoring which exits it prints"
    )
    assert corrected_queries == absent_queries, (
        "the refusal issued a different number of queries for the two "
        "deliveries, so it is reading per case to decide what to print"
    )

    # The stronger half: printing the exits must cost nothing at all. A read
    # taken on every post_deploy refusal alike would survive the comparison
    # above, because both deliveries would pay it. Rendering the same row in a
    # phase that appends no recovery isolates exactly what the exits cost.
    baseline = _CountingConn(test_db)
    done_gate_refusal_errors(
        baseline, [_verification_row(with_corrected)], name="YOKE item"
    )
    assert corrected_queries == baseline.queries, (
        "rendering the post_deploy exits issued "
        f"{corrected_queries - baseline.queries} query(s) beyond the same row "
        "in a phase that prints no exits, so the refusal path is reading to "
        "decide what to print"
    )
