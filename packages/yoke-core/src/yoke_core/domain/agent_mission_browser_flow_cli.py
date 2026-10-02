"""Lease-authorized saved-profile approvals for exploratory walkers."""

from __future__ import annotations

import argparse
import json
import sys

from yoke_core.domain.agent_mission_host_command_cli import (
    add_mission_subject_arguments,
    resolve_mission_contract,
)

PROG = "yoke qa mission browser-flow"


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Complete this mission's own emitted browser approval from its machine's saved signed-in profile.",
        epilog=(
            "First install the candidate and start its own flow on the registered "
            "Test Machine. Capture the actual installer output in an owner-only "
            "file under the mission scratch directory, and reach the browser-wait "
            "state using the mission's host-command. Pass that file and the "
            "installer's completion text here. The shared typed recipe gate "
            "validates the exact printed URL/code against .yoke/browser-flows.json "
            "and the immutable case target, restores the saved profile if needed, "
            "proves the visible approval control, and waits for terminal completion. "
            "Missing or expired sign-in returns a precise human_gate; the operator "
            "signs in personally and captures a separate fresh baseline before "
            "rerunning the same case. Never log in, paste a link, use another "
            "request, or change machine security settings. This command records "
            "bounded browser evidence, not a QA verdict. Exit 0 completed, "
            "2 invalid mission/declaration/transcript, 3 refused or human_gate."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_mission_subject_arguments(parser)
    parser.add_argument("--transcript-path", required=True)
    parser.add_argument("--completion-text", action="append", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parsed = parser.parse_args(args)
    if not 1 <= parsed.timeout_seconds <= 900:
        parser.error("--timeout-seconds must be between 1 and 900")
    if len(parsed.completion_text) > 16 or any(
        not text or len(text) > 256 for text in parsed.completion_text
    ):
        parser.error("--completion-text needs 1..16 bounded nonempty markers")
    contract = resolve_mission_contract(parsed, prog=PROG)
    if contract is None:
        return 2
    try:
        from yoke_core.domain.machine_qa_host_control import (
            register_test_machine_host_control,
        )
        from yoke_core.domain.machine_qa_mission_browser_flow import (
            execute_agent_mission_browser_flow,
        )

        register_test_machine_host_control()
        result = execute_agent_mission_browser_flow(
            contract,
            execution_id=parsed.execution_id,
            transcript_path=parsed.transcript_path,
            completion_text=parsed.completion_text,
            timeout_seconds=parsed.timeout_seconds,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "execution_id": parsed.execution_id,
                "requirement_id": parsed.requirement_id,
                **result,
            },
            sort_keys=True,
        )
    )
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
