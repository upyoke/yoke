"""Remote paths reserved for the Machine QA fixture runner."""

FIXTURE_ROOT = "/tmp/yoke-machine-qa-fixtures"
FAKE_API_SERVER_PATH = f"{FIXTURE_ROOT}/fake_yoke_api.py"
SERVICE_MANAGER_PATH = f"{FIXTURE_ROOT}/service_manager.py"
SOURCE_CHECKOUT_ASSERTION_PATH = f"{FIXTURE_ROOT}/source_checkout_assertion.py"
STARTUP_MARKER_ASSERTION_PATH = f"{FIXTURE_ROOT}/startup_marker_assertion.py"


__all__ = [
    "FAKE_API_SERVER_PATH",
    "FIXTURE_ROOT",
    "SERVICE_MANAGER_PATH",
    "SOURCE_CHECKOUT_ASSERTION_PATH",
    "STARTUP_MARKER_ASSERTION_PATH",
]
