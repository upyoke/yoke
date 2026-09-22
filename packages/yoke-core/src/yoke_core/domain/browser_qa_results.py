"""Browser QA result dataclasses and the local logger.

Hosts ``RequirementOutcome``, ``RunResult`` and ``ScenarioResult`` (returned
to callers and serialized to stdout JSON) plus the ``_log`` helper that
prefixes stderr messages. These are the smallest stable surface in the
Browser QA orchestrator and have no internal collaborators, so they live in
their own sibling module.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from yoke_contracts.qa_artifact_read import artifact_read_command


@dataclass
class RunResult:
    requirement_id: int
    qa_kind: str
    verdict: str
    qa_run_id: Optional[int] = None
    execution_status: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    artifact_ids: List[int] = field(default_factory=list)
    errors: str = ""
    expected_screenshots: int = 0
    recorded_screenshots: int = 0
    vacuous_absences: List[Dict[str, Any]] = field(default_factory=list)
    code_identity: Dict[str, str] = field(default_factory=dict)
    sign_in: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "requirement_id": self.requirement_id,
            "qa_kind": self.qa_kind,
            "verdict": self.verdict,
        }
        if self.qa_run_id is not None:
            d["qa_run_id"] = self.qa_run_id
        if self.execution_status is not None:
            d["execution_status"] = self.execution_status
        # The capture paths below are this process's scratch, which the
        # reviewer's own path guard refuses; the registered ids and their
        # read commands are what a reviewer can actually open.
        d["artifacts"] = self.artifacts
        d["artifact_ids"] = self.artifact_ids
        d["artifact_reads"] = [
            artifact_read_command(self.requirement_id, artifact_id)
            for artifact_id in self.artifact_ids
        ]
        if self.errors:
            d["errors"] = self.errors
        if self.expected_screenshots > 0:
            d["expected_screenshots"] = self.expected_screenshots
            d["recorded_screenshots"] = self.recorded_screenshots
        if self.vacuous_absences:
            d["vacuous_absences"] = self.vacuous_absences
        if self.code_identity:
            d["code_identity"] = self.code_identity
        if self.sign_in:
            d["sign_in"] = self.sign_in
        return d


@dataclass
class RequirementOutcome:
    """Outcome of processing a single qa_requirement.

    Returned by ``_process_requirement`` to ``execute_scenario`` so the latter
    can update its aggregate ``ScenarioResult`` (verdict, executed/skipped
    counters, runs list) without sharing mutable state with the loop.
    """

    run_result: RunResult
    skipped: bool = False
    executed: bool = False
    capture_failed: bool = False
    env_failure: bool = False


@dataclass
class ScenarioResult:
    verdict: str = "pass"
    runs: List[RunResult] = field(default_factory=list)
    skipped: int = 0
    executed: int = 0
    note: str = ""

    def to_json(self) -> str:
        d: Dict[str, Any] = {
            "verdict": self.verdict,
            "runs": [r.to_dict() for r in self.runs],
        }
        if self.skipped > 0:
            d["skipped"] = self.skipped
            d["executed"] = self.executed
        if self.note:
            d["note"] = self.note
        return json.dumps(d)


def _log(msg: str) -> None:
    print(f"[browser-run-scenario] {msg}", file=sys.stderr)
