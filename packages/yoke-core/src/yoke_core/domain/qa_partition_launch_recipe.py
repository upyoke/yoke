"""Name the exact command and launch that own one QA partition."""

import shlex

from yoke_core.domain.deployment_run_recovery_command import yoke_command


def partition_launch_recipe(
    *, project: str, subject: str, leg: str, key: str, command: str, attempt: str = "1"
) -> str:
    launch_args = shlex.join([
        "session-control", "launch", "create", "--project", project,
        "--level", "LEVEL", "--surface", "CLI",
        "--raw-instructions", "--stdin", "--idempotency-key",
        f"qa-walk:{subject}:{leg}:{key}:{attempt}",
    ])
    instructions = (
        "Use delegated QA access for the assigned partition. Do not acquire "
        "an item work claim. Follow .yoke/docs/verification/walking.md#run-and-report. "
        f"Begin with: {command}"
    )
    return f"printf '%s\\n' {shlex.quote(instructions)} | {yoke_command()} {launch_args}"


def run_partition_subject(run_id: str, stage: str, plan: str, project: str) -> str:
    return shlex.join([
        "--deployment-run-id", run_id, "--stage", stage, "--plan", plan, "--project", project,
    ])
