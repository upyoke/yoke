"""QA gate type definitions — GateTarget, GateResult, LatestCodeRef.

Extracted from qa_gates.py. These are pure data types with no DB or
subprocess dependencies, making them safe to import anywhere without
pulling in the heavier gate-check logic.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class GateTarget:
    """Parsed gate-check target: either an item ID or epic_id:task_num."""

    item_id: Optional[int] = None
    epic_id: Optional[int] = None
    task_num: Optional[int] = None

    @classmethod
    def parse(cls, raw: str) -> "GateTarget":
        if ":" in raw:
            parts = raw.split(":", 1)
            return cls(epic_id=int(parts[0]), task_num=int(parts[1]))
        return cls(item_id=int(raw))

    def where_clause(self) -> Tuple[str, tuple]:
        """Return (SQL fragment, params) for WHERE filtering."""
        if self.item_id is not None:
            return "item_id = %s", (self.item_id,)
        return "epic_id = %s AND task_num = %s", (self.epic_id, self.task_num)

    def display_name(self) -> str:
        if self.item_id is not None:
            return f"YOK-{self.item_id}"
        return f"epic {self.epic_id}/task {self.task_num}"


@dataclass
class GateResult:
    """Result of a gate check."""

    passed: bool
    errors: List[str] = field(default_factory=list)

    def emit_errors(self) -> None:
        for line in self.errors:
            print(line, file=sys.stderr)


@dataclass(frozen=True)
class LatestCodeRef:
    """Latest code identity for a target branch."""

    branch: Optional[str] = None
    sha: Optional[str] = None
    timestamp: Optional[str] = None
