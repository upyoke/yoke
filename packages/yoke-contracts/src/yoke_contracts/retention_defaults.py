"""Shipped retention windows for one universe's disposable records."""

RETENTION_KEY = "retention"
DEFAULT_SEVERITY_DAYS = {
    "DEBUG": 1,
    "INFO": 30,
    "WARN": 90,
    "ERROR": 180,
    "FATAL": 365,
    "STATUS": 365,
}
DEFAULT_EVENT_DAYS = {
    "YokeFunctionCalled": 7,
    "HookDispatchTelemetry": 7,
    "HarnessToolCallStarted": 7,
    "HarnessToolCallCompleted": 7,
}
DEFAULT_WINDOWS = {
    "token_check_success": 7,
    "token_check_other": 90,
    "token_lifecycle": 365,
    "replay": 7,
    "dispatch_intents": 30,
    "tool_calls": 7,
    "agent_messages": 30,
    "launches": 30,
    "evidence_fetches": 7,
    "settled_waits": 30,
    "expired_security": 1,
    "snapshot_uploads": 7,
}
