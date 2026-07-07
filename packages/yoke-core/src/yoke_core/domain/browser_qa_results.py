"""Browser QA result dataclasses and the local logger.

Hosts ``RunResult`` and ``ScenarioResult`` (returned to callers and serialized
to stdout JSON) plus the ``_log`` helper that prefixes stderr messages. These
are the smallest stable surface in the Browser QA orchestrator and have no
internal collaborators, so they live in their own sibling module.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
        d: Dict[str, Any] = {
            "requirement_id": self.requirement_id,
            "qa_kind": self.qa_kind,
            "verdict": self.verdict,
        }
        if self.qa_run_id is not None:
            d["qa_run_id"] = self.qa_run_id
        if self.execution_status is not None:
            d["execution_status"] = self.execution_status
        d["artifacts"] = self.artifacts
        if self.errors:
            d["errors"] = self.errors
        if self.expected_screenshots > 0:
            d["expected_screenshots"] = self.expected_screenshots
            d["recorded_screenshots"] = self.recorded_screenshots
        if self.code_identity:
            d["code_identity"] = self.code_identity
        return d


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
