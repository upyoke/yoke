"""Result-file contract for done-transition."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

@dataclass
class TransitionResult:
    """Tracks done-transition state for the result file."""

    item: str = ""
    exit_code: int = 0
    old_status: str = ""
    new_status: str = ""
    merge_ran: bool = False
    already_completed: bool = False
    discovery_unreviewed: int = 0
    steps_completed: list[str] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def add_step(self, step: str) -> None:
        self.steps_completed.append(step)

    def write(self, path: str) -> None:
        """Write result JSON atomically."""
        data = {
            "item": self.item,
            "exit_code": self.exit_code,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "merge_ran": self.merge_ran,
            "already_completed": self.already_completed,
            "discovery": {
                "unreviewed_ouroboros": self.discovery_unreviewed,
            },
            "steps_completed": self.steps_completed,
            "warnings": self.warnings,
        }
        tmp = f"{path}.tmp.{os.getpid()}"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def fail(self, path: str, code: int, step: str | None = None) -> int:
        """Record failure and write result file."""
        self.exit_code = code
        if step:
            self.add_step(step)
        self.write(path)
        return code
