"""QA schema examples in rendered agent packets."""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac


def test_main_agent_packet_teaches_qa_requirement_run_columns() -> None:
    body = sac.render_role_packet("main_agent")
    for text in (
        "yoke qa requirement list --item PREFIX-N",
        "yoke qa run list --requirement-id <id>",
        "yoke qa run get --run-id <id>",
        "qa_requirements.id is the PK",
        "qa_runs.qa_requirement_id is the FK",
        "raw_result (result payload)",
    ):
        assert text in body
    assert "requirement_id, success_policy" not in body
    assert "SELECT id, requirement_id, result" not in body


def test_qa_packet_lists_live_qa_requirements_columns() -> None:
    body = sac.render_topic_packet("qa")
    for column in (
        "deployment_run_id",
        "target_env",
        "capability_requirements",
        "suite_id",
        "waived_at",
        "waiver_rationale",
        "waiver_source",
    ):
        assert column in body, f"qa_requirements column {column!r} missing from qa packet"


def test_qa_packet_lists_live_qa_runs_columns() -> None:
    body = sac.render_topic_packet("qa")
    for column in (
        "score",
        "confidence",
        "duration_ms",
        "started_at",
        "completed_at",
        "execution_status",
    ):
        assert column in body, f"qa_runs column {column!r} missing from qa packet"
    assert "execution_status` is the browser capture outcome" in body


def test_qa_packet_carries_canonical_unsatisfied_verification_select() -> None:
    body = sac.render_topic_packet("qa")
    assert "Canonical unsatisfied-verification SELECT" in body
    assert "FROM qa_requirements qr WHERE qr.item_id = %s" in body
    assert "qr.qa_phase = 'verification' AND qr.waived_at IS NULL" in body
    assert "NOT EXISTS (SELECT 1 FROM qa_runs qrun" in body
    assert "qrun.qa_requirement_id = qr.id AND qrun.verdict = 'pass'" in body


def test_qa_packet_carries_requirement_add_ac_verification_example() -> None:
    body = sac.render_topic_packet("qa")
    assert "Add a QA requirement — ac_verification variant" in body
    assert (
        "yoke qa requirement add "
        "--item PREFIX-N --qa-kind ac_verification --qa-phase verification "
        "--blocking-mode blocking --requirement-source ac_derived"
    ) in body
    assert '{"min_runs":N,"min_pass":N}' in body
    # Epic-task / deployment-run attachment stays operator-debug.
    assert "requirement-add --epic-id E --task-num K" in body


def test_qa_packet_carries_requirement_add_browser_smoke_example() -> None:
    body = sac.render_topic_packet("qa")
    assert "Add a QA requirement — browser_smoke variant" in body
    assert "--qa-kind browser_smoke --qa-phase verification" in body
    assert "--capability-requirements browser-qa" in body
    assert '--success-policy \'{"steps":[{"action":"navigate"' in body
    assert "Browser kinds (`browser_smoke`, `browser_diff`) REQUIRE" in body


def test_qa_packet_carries_run_add_agent_ac_verification_example() -> None:
    body = sac.render_topic_packet("qa")
    assert (
        "Add a QA run verdict — agent × ac_verification (inline raw_result)"
        in body
    )
    assert (
        "yoke qa run add "
        "--requirement-id R --executor-type agent "
        "--qa-kind ac_verification --verdict pass "
    ) in body
    assert "`--qa-kind` defaults to the requirement's kind" in body


def test_qa_packet_carries_run_add_browser_substrate_smoke_example() -> None:
    body = sac.render_topic_packet("qa")
    assert (
        "Add a QA run verdict — browser_substrate × browser_smoke (file evidence)"
        in body
    )
    assert "--executor-type browser_substrate" in body
    assert "--qa-kind browser_smoke --verdict pass" in body
    assert '--raw-result \'{"status":"captured"}\'' in body
    assert "yoke qa artifact add --requirement-id R --run-id RUN" in body
    assert '"/tmp/browser-evidence/login.png"' in body


def test_qa_packet_replaces_run_add_trailing_parenthetical() -> None:
    body = sac.render_topic_packet("qa")
    assert (
        "CLI adapter `qa run-add` accepts `--raw-result-file PATH` for "
        "multi-line evidence blobs."
    ) not in body
    assert "yoke qa run get --run-id <id>" in body
    assert "Registered read qa.run.get" in body
    assert "no registered id" not in body
