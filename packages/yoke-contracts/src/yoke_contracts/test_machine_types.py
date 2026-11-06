"""Machine-local result types shared by Test Machine harness adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HostActionResult:
    """A secret-free machine action result safe to submit as evidence."""

    ok: bool
    evidence: dict[str, Any]
    error_code: str | None = None


__all__ = ["HostActionResult"]
