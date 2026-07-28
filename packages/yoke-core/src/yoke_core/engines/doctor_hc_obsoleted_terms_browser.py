"""Retired duplicate Browser execution vocabulary."""

RETIRED_BROWSER_HARNESS_FACADE_PATTERN = r"\byoke_harness" + r"\." + r"browser_qa\b"
RETIRED_BROWSER_HARNESS_RUNNER_PATTERN = (
    r"\byoke_harness"
    + r"\."
    + r"browser_qa_(runner|requirement|artifacts|checks|results)\b"
)
RETIRED_SCREENSHOT_BRIDGE_MODULE_PATTERN = (
    r"\byoke_core" + r"\." + r"domain\.qa_evidence_bridge\b"
)
RETIRED_SCREENSHOT_BRIDGE_HANDLER_PATTERN = r"\bqa_browser_" + r"evidence\b"
RETIRED_SCREENSHOT_BRIDGE_FUNCTION_PATTERN = (
    r"\bqa" + r"\." + r"screenshot_evidence\.(pending_count|satisfy)\b"
)
RETIRED_SCREENSHOT_BRIDGE_CLI_PATTERN = (
    r"\byoke\s+qa\s+" + r"screenshot-evidence\s+(pending-count|satisfy)\b"
)
RETIRED_SCREENSHOT_BRIDGE_RAW_CLI_PATTERN = r"\bsatisfy-" + r"screenshot-evidence\b"
RETIRED_SCREENSHOT_BRIDGE_HELPER_PATTERN = r"\bcmd_satisfy_" + r"screenshot_evidence\b"

BROWSER_RETIREMENT_PATTERNS = (
    RETIRED_BROWSER_HARNESS_FACADE_PATTERN,
    RETIRED_BROWSER_HARNESS_RUNNER_PATTERN,
    RETIRED_SCREENSHOT_BRIDGE_MODULE_PATTERN,
    RETIRED_SCREENSHOT_BRIDGE_HANDLER_PATTERN,
    RETIRED_SCREENSHOT_BRIDGE_FUNCTION_PATTERN,
    RETIRED_SCREENSHOT_BRIDGE_CLI_PATTERN,
    RETIRED_SCREENSHOT_BRIDGE_RAW_CLI_PATTERN,
    RETIRED_SCREENSHOT_BRIDGE_HELPER_PATTERN,
)

BROWSER_RETIREMENT_LABELS = {
    RETIRED_BROWSER_HARNESS_FACADE_PATTERN: ("retired duplicate Browser runner facade"),
    RETIRED_BROWSER_HARNESS_RUNNER_PATTERN: ("retired duplicate Browser runner module"),
    RETIRED_SCREENSHOT_BRIDGE_MODULE_PATTERN: (
        "retired screenshot-to-AC bridge module"
    ),
    RETIRED_SCREENSHOT_BRIDGE_HANDLER_PATTERN: (
        "retired screenshot-to-AC bridge handler"
    ),
    RETIRED_SCREENSHOT_BRIDGE_FUNCTION_PATTERN: (
        "retired screenshot-to-AC bridge function"
    ),
    RETIRED_SCREENSHOT_BRIDGE_CLI_PATTERN: ("retired screenshot-to-AC bridge command"),
    RETIRED_SCREENSHOT_BRIDGE_RAW_CLI_PATTERN: (
        "retired raw screenshot-to-AC bridge command"
    ),
    RETIRED_SCREENSHOT_BRIDGE_HELPER_PATTERN: (
        "retired screenshot-to-AC bridge helper"
    ),
}

BROWSER_RETIREMENT_PATH_ALLOWLIST = {
    RETIRED_SCREENSHOT_BRIDGE_RAW_CLI_PATTERN: (
        # The zero-shell closeout inventory preserves names of deleted shell
        # tests as audit evidence; it is not a runnable or taught command.
        "runtime/api/tools/shell_inventory",
        "packages/yoke-core/src/yoke_core/tools/shell_inventory",
    ),
}

__all__ = [
    "BROWSER_RETIREMENT_LABELS",
    "BROWSER_RETIREMENT_PATH_ALLOWLIST",
    "BROWSER_RETIREMENT_PATTERNS",
    "RETIRED_BROWSER_HARNESS_FACADE_PATTERN",
    "RETIRED_BROWSER_HARNESS_RUNNER_PATTERN",
    "RETIRED_SCREENSHOT_BRIDGE_CLI_PATTERN",
    "RETIRED_SCREENSHOT_BRIDGE_FUNCTION_PATTERN",
    "RETIRED_SCREENSHOT_BRIDGE_HANDLER_PATTERN",
    "RETIRED_SCREENSHOT_BRIDGE_HELPER_PATTERN",
    "RETIRED_SCREENSHOT_BRIDGE_MODULE_PATTERN",
    "RETIRED_SCREENSHOT_BRIDGE_RAW_CLI_PATTERN",
]
