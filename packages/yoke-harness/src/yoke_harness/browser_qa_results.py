"""Result types and shared constants for product browser QA."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef


Dispatcher = Callable[[str, TargetRef, Dict[str, Any]], FunctionCallResponse]
SCREENSHOT_ACTIONS = frozenset({"screenshot"})
BROWSER_EXECUTOR_TYPE = "browser_substrate"
QA_ARTIFACT_STORAGE_KIND = "qa-artifacts"
SCRATCH_ROOT_ENV = "YOKE_SCRATCH_ROOT"
RUN_ENV_KEYS = ("YOKE_RUN_ID", "YOKE_EXECUTION_ID", "GITHUB_RUN_ID")
SESSION_ENV_KEYS = ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID")


@dataclass
class RunResult:
    requirement_id: int
    qa_kind: str
    verdict: str
    qa_run_id: Optional[int] = None
    execution_status: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    errors: str = ""
    expected_screenshots: int = 0
    recorded_screenshots: int = 0
    code_identity: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "requirement_id": self.requirement_id,
            "qa_kind": self.qa_kind,
            "verdict": self.verdict,
            "artifacts": self.artifacts,
        }
        if self.qa_run_id is not None:
            payload["qa_run_id"] = self.qa_run_id
        if self.execution_status is not None:
            payload["execution_status"] = self.execution_status
        if self.errors:
            payload["errors"] = self.errors
        if self.expected_screenshots > 0:
            payload["expected_screenshots"] = self.expected_screenshots
            payload["recorded_screenshots"] = self.recorded_screenshots
        if self.code_identity:
            payload["code_identity"] = self.code_identity
        return payload


@dataclass
class ScenarioResult:
    verdict: str = "pass"
    runs: List[RunResult] = field(default_factory=list)
    skipped: int = 0
    executed: int = 0
    note: str = ""

    def to_json(self) -> str:
        payload: Dict[str, Any] = {
            "verdict": self.verdict,
            "runs": [run.to_dict() for run in self.runs],
        }
        if self.skipped > 0:
            payload["skipped"] = self.skipped
            payload["executed"] = self.executed
        if self.note:
            payload["note"] = self.note
        return json.dumps(payload)


@dataclass
class RequirementOutcome:
    run_result: RunResult
    skipped: bool = False
    executed: bool = False
    capture_failed: bool = False
    env_failure: bool = False


def scenario_exit_code(result: ScenarioResult) -> int:
    if result.verdict == "error" or result.note in {
        "no_browser_requirements",
        "unreachable",
        "daemon_failure",
        "no_base_url",
        "vacuous_pass_prevented",
        "sha_mismatch",
        "context_unavailable",
    }:
        return 2
    if result.verdict == "fail":
        return 1
    return 0


def log(message: str) -> None:
    print(f"[browser-run-scenario] {message}", file=sys.stderr)


__all__ = [
    "BROWSER_EXECUTOR_TYPE",
    "Dispatcher",
    "QA_ARTIFACT_STORAGE_KIND",
    "RUN_ENV_KEYS",
    "RequirementOutcome",
    "RunResult",
    "SCREENSHOT_ACTIONS",
    "SCRATCH_ROOT_ENV",
    "SESSION_ENV_KEYS",
    "ScenarioResult",
    "log",
    "scenario_exit_code",
]
