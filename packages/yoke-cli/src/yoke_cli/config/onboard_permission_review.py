"""Permission disclosure from the launch declarations used by native workers."""

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS
from yoke_contracts.session_control import launch_permission_bypass as bypass


SETUP_PERMISSION_DISCLOSURE = (
    "Setup configures installed agent tools to run commands without asking for approval, "
    "with their sandbox disabled, across this machine.",
    "Workers also bypass command approval; Codex workers bypass sandbox and CLI hook-trust checks.",
)


def permission_summary(*, expanded: bool) -> list[str]:
    lines = []
    if expanded:
        lines.extend(
            f"{harness} worker CLI: {' '.join(bypass.cli_bypass_arguments(harness))}"
            for harness in CANONICAL_HARNESS_IDS
        )
        thread = bypass.codex_thread_bypass_parameters()
        lines.append(
            f"Codex app-server worker: approvalPolicy={thread['approvalPolicy']}, "
            f"sandbox={thread['sandbox']}; CLI hook-trust flags do not apply. "
            "Operator-opened sessions use their saved settings."
        )
    return lines
