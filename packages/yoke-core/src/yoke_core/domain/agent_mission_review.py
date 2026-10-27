"""Main-owned review dispatch for exploratory mission bundles."""

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
            f"target digest {target_digest}. Dispatch informed subagents, one "
            "walker at a time, passing walker_dispatches[].prompt to its walker unchanged: "
            "host missions retain their Test Machine, and each host walk resets "
            "it on walk-start and restores it on walk-end. A walker turn is "
            "atomic and cannot ask the operator or send Fleet mail. "
            "When it returns HUMAN_GATE, append the action, why, observed "
            "state, and resume point to the item's Progress Log. Verify the "
            "executing host, browser substrate, project profile, target URL, "
            "and live access route from this run. A Test Machine inventory "
            "is not where the browser ran. Managed sign-in is `yoke browser "
            "authorize --identity NAME` on that host; `yoke qa browser setup` "
            "only starts the runtime. A host-native browser uses its declared "
            "human access surface, not a fabricated authorize command. Put no "
            "credential content in the request. Preview with `yoke say "
            "--preview --steering --json`. steering_recipient.state delivered "
            "means a live seat covers this item: send `printf %s BODY | yoke "
            "say --steering --stdin --idempotency-key KEY` and read the "
            "receipt. awaiting_seat is not delivery; cancel it with `yoke "
            "messages cancel MESSAGE-ID` and use the owner path. Read `yoke "
            "items get PREFIX-N owner` (`NAME (actor id: N)`); `unassigned` or "
            "`unknown actor` is unresolved: report it. Confirm with `yoke say "
            "--preview --actor ACTOR --json`. actor_recipient_not_human or "
            "actor_recipient_forbidden is a named refusal, not a successful "
            "ask. Otherwise send `printf %s BODY | yoke say --actor ACTOR "
            "--stdin --idempotency-key KEY`. --item addresses the current "
            "holder, not the human owner. The body names the item, execution, "
            "requirement, action, access route, and resume point, and asks "
            "that the answer return with `yoke say --item PREFIX-N --stdin`. "
            "Acknowledgement is read, not sign-in proof. Record the answer, "
            "verify the action, and dispatch a fresh walker with the resume "
            "state. Use the declared continuation when the held host must "
            "keep its state; do not start an ordinary reset run. "
            "A host mission whose sign-in or GUI-opened session must survive declares "
            "starting state as_is (unrun case: `yoke qa requirement update --field "
            "starting_state`); the walker opens sessions and approves codes itself "
            "and requests human help for real password, 2FA or payment steps. "
            "Keep the fresh target free of a source checkout; the informed "
            "walker uses controller context and installed target guidance. "
            + stopped_mission_guidance(
                subject_flag,
                execution_id,
                has_host=any(needs_test_machine(case) for case in cases),
            )
            + "Review every non-mission case yourself from its transcript and "
            "artifact-read commands. Review ranked reports and evidenced workarounds. "
            "Never pass a case whose workaround touched its tested behavior "
            "(such as CLI replacing browser approval); rerun preserving that "
            "boundary. Choose final verdicts and submit exactly one row "
            f"for each of the {len(cases)} bundle cases in one complete batch. "
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
            "authority. Preserve it as historical evidence; do not dispatch "
            "walkers, access the leased host, or submit verdicts."
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
