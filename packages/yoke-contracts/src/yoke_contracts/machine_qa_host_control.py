"""Finite operations and baselines carried by host-control contracts."""

from typing import Literal

HOST_CONTROL_PROTOCOL = "host-control-v1"
HOST_TEST_COMMAND = "/bin/test"
GUI_SESSION_CONTEXT = "gui"
AGENT_MISSION_ARTIFACT_LIMIT = 100
REQUIRED_SESSION_CONTEXT_FIELD = "required_session_context"
VERIFICATION_CHECKS = ("connection", "terminal_bridge")
HOST_BASELINES = ("fresh-host", "shell-preconfigured")
HOST_BASELINE_END_STATE = {
    HOST_BASELINES[0]: ("the host carries its captured user state and no Yoke at all"),
    HOST_BASELINES[1]: (
        "the host carries its captured user state plus the current Yoke "
        "launcher on both shell surfaces; it is NOT a fresh host"
    ),
}
# The destructive operations a person runs against one machine, each recorded
# against the machine under its own name so the last one is always readable.
RESET_OPERATION = "reset"
GOLDEN_CAPTURE_OPERATION = "golden_capture"
BRIDGE_DIAGNOSE_OPERATION = "bridge_diagnose"
VERIFY_OPERATION = "verify"
SCREENSHOT_OPERATION = "screenshot"
PERSISTENT_TERMINAL_BRIDGE_CHECKS = (
    "tmux_session",
    "tmux_input_transcript",
    "gui_screenshot",
)
TEST_MACHINE_OPERATIONS = (
    VERIFY_OPERATION,
    RESET_OPERATION,
    GOLDEN_CAPTURE_OPERATION,
    BRIDGE_DIAGNOSE_OPERATION,
    SCREENSHOT_OPERATION,
)

RECORDED_TEST_MACHINE_OPERATIONS = tuple(
    operation for operation in TEST_MACHINE_OPERATIONS if operation != VERIFY_OPERATION
)

HostControlOperation = Literal[
    "verify",
    "reset",
    "golden_capture",
    "bridge_diagnose",
    "screenshot",
    "case",
    "plan_case",
]
