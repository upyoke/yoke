"""Name the exact command and launch that own one QA partition."""

import shlex

from yoke_core.domain.deployment_run_recovery_command import yoke_command


PINNED_WALK_SELECTION = (
    "To pin a CLI surface, replace --level LEVEL with --surface SURFACE --model MODEL "
    "and, if needed, --reasoning-effort EFFORT."
)


def partition_launch_command(
    *, project: str, subject: str, leg: str, key: str, attempt: str = "1",
    launcher: str = "yoke",
) -> str:
    launch_args = shlex.join([
        "session-control", "launch", "create", "--project", project, "--level", "LEVEL",
        "--raw-instructions", "--stdin", "--idempotency-key",
        f"qa-walk:{subject}:{leg}:{key}:{attempt}",
    ])
    return f"{launcher} {launch_args}"


def partition_launch_recipe(
    *, project: str, subject: str, leg: str, key: str, command: str, attempt: str = "1"
) -> str:
    launch = partition_launch_command(
        project=project, subject=subject, leg=leg, key=key, attempt=attempt,
        launcher=yoke_command(),
    )
    instructions = (
        "Use delegated QA access for the assigned partition. Do not acquire "
        "an item work claim. Follow .yoke/docs/verification/walking.md#run-and-report. "
        f"Begin with: {command}"
    )
    return f"printf '%s\\n' {shlex.quote(instructions)} | {launch}"


def run_partition_subject(run_id: str, stage: str, plan: str, project: str) -> str:
    return shlex.join([
        "--deployment-run-id", run_id, "--stage", stage, "--plan", plan, "--project", project,
    ])
