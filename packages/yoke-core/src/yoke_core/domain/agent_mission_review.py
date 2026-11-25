"""Main-thread instructions for exploratory mission bundles."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.qa_case_starting_state import needs_test_machine

from yoke_contracts.machine_qa_execution import (
    AGENT_MISSION_ARTIFACT_LIMIT,
)
from yoke_core.domain.agent_mission_browser_identities import (
    mission_browser_settings,
)
from yoke_core.domain.qa_mission_stop_settlement import stopped_mission_guidance
from yoke_core.domain.qa_review_evidence import case_artifact_read_commands
from yoke_core.domain.qa_plan_review_subject import subject_flag as review_subject_flag
from yoke_core.domain.qa_review_verdict_modes import (
    ALL_REVIEW_VERDICTS,
    inconclusive_verdict_guidance,
    verdict_enum_text,
)


from yoke_core.domain.agent_mission_brief import (
    _screen_recording_warning,
    _walker_dispatch,
)


def agent_mission_dispatch_contract(
    bundle: Mapping[str, Any],
    *,
    allowed_verdicts: tuple[str, ...] = ALL_REVIEW_VERDICTS,
    conn: Any = None,
) -> dict[str, Any]:
    """Return instructions that keep mission ownership in the main agent."""
    bundle_id = str(bundle["bundle_id"])
    digest = str(bundle["bundle_digest"])
    execution_id = str(bundle["execution_id"])
    subject = bundle["subject"]
    execution_target = bundle.get("execution_target")
    subject_flag = review_subject_flag(subject, execution_target)
    target_digest = str(bundle.get("execution_target_digest") or "")
    environment = (
        execution_target.get("environment")
        if isinstance(execution_target, Mapping)
        else None
    )
    authority_bound = (
        isinstance(environment, Mapping)
        and bool(str(environment.get("name") or "").strip())
        and bool(target_digest)
    )
    authority = {
        "state": "bound" if authority_bound else "unavailable",
        "environment": (
            str(environment.get("name") or "") if authority_bound else None
        ),
        "execution_target_digest": target_digest if authority_bound else None,
    }
    cases = list(bundle["cases"])
    browser_settings = mission_browser_settings(conn, bundle)
    walker_dispatches = [
        {
            "requirement_id": int(case["requirement_id"]),
            **_walker_dispatch(
                case,
                execution_id=execution_id,
                subject_flag=subject_flag,
                browser_settings=browser_settings,
                execution_target=execution_target or {},
            ),
        }
        for case in cases
        if case.get("capture_runner") == "agent_mission"
    ]
    main_review_requirement_ids = [
        int(case["requirement_id"])
        for case in cases
        if case.get("capture_runner") != "agent_mission"
    ]
    artifact_read_commands = case_artifact_read_commands(cases)
    if authority_bound:
        prompt = (
            f"Own exploratory QA bundle {bundle_id} ({digest}) as the main "
            f"agent for immutable environment {authority['environment']} at "
            f"target digest {target_digest}. Walk each mission in this session's "
            "main thread, one at a time, following walker_dispatches[].prompt and "
            ".yoke/docs/verification/walking.md. Save evidence with "
            "`yoke qa artifact add` as you go. Record each case's verdict from "
            "what you saw, naming the evidence it rests on, then submit. "
            "For a password, 2FA or payment gate, verify this run's host, "
            "browser, profile, target URL and human access route. Preview "
            "with `yoke say --preview --steering --json`; send with "
            "`yoke say --steering --stdin --idempotency-key KEY` when the "
            "preview says delivered. If steering is unavailable, look up the "
            "item owner with `yoke items get PREFIX-N owner`, preview "
            "`yoke say --preview --actor ACTOR --json`, and send with "
            "`yoke say --actor ACTOR --stdin --idempotency-key KEY`. Verify the "
            "receipt; report an unresolved owner or refusal as a blocker. "
            "Name the plan, execution, requirement, action, access route and "
            "resume point. Keep credentials out of the request and ask for the "
            "answer with `yoke say --session YOUR_SESSION_ID --stdin`. Run "
            "`yoke sessions touch --mode parked --reason qa-human-gate` and end "
            "the turn. On return, verify the human action and continue with "
            "host-command on the held lease. Use the declared continuation if "
            "the held host must keep its state. "
            + stopped_mission_guidance(
                subject_flag,
                execution_id,
                has_host=any(needs_test_machine(case) for case in cases),
            )
            + "Read every non-mission case's capture and record its verdict the "
            "same way. Record findings and workarounds with their evidence. "
            "If a workaround changed the behavior under test, rerun preserving "
            "that behavior before recording a pass. Submit exactly one row "
            f"for each of the {len(cases)} bundle cases in one complete batch. "
            "Cite artifact N from that case in each pass or fail rationale, "
            "or run N for its capture run when the case has no artifacts. "
            + inconclusive_verdict_guidance(allowed_verdicts)
            + _screen_recording_warning(cases)
        )
        submit_command = (
            f"yoke qa plan review-submit {subject_flag} "
            f"--execution-id {execution_id} --bundle-id {bundle_id} "
            f"--bundle-digest {digest} --stdin"
        )
    else:
        prompt = (
            f"QA bundle {bundle_id} ({digest}) has no immutable target "
            "authority. Preserve it as historical evidence; do not walk missions or "
            "access the leased host, or submit verdicts."
        )
        submit_command = None
        walker_dispatches = []
    return {
        "dispatch_kind": "main_agent_mission",
        "role": "main_agent",
        "subagent_type": None,
        "authority": authority,
        "walker_dispatches": walker_dispatches,
        "main_review_requirement_ids": main_review_requirement_ids,
        "artifact_limit": AGENT_MISSION_ARTIFACT_LIMIT,
        "artifact_read_commands": artifact_read_commands,
        "result_schema": {
            "verdicts": [
                {
                    "requirement_id": "integer",
                    "verdict": verdict_enum_text(allowed_verdicts),
                    "rationale": "non-empty written report",
                }
            ]
        },
        "prompt": prompt,
        "host_wait_schema": {
            "host_wait": {
                "test_machine": "test machine name",
                "rationale": "lease evidence",
            }
        },
        "submit_command": submit_command,
    }


__all__ = ["agent_mission_dispatch_contract"]
