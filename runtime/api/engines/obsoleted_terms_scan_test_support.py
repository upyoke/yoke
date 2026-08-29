"""Shared values for obsoleted-term repository scanner tests."""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_report import DoctorArgs


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Cannot locate repo root")


REPO_ROOT = _repo_root()


def retired_parent_epic_symbol() -> str:
    """Build the retired symbol without embedding it in scanner source."""
    return "items" + "." + "epic"


def db_router_items_command(
    verb: str,
    public_ref: str,
    field: str,
    value: str = "",
) -> str:
    """Build the legacy command shape exercised by the scanner."""
    parts = [
        "python3 -m yoke_core.cli.db_router",
        "items",
        verb,
        public_ref,
        field,
    ]
    if value:
        parts.append(value)
    return " ".join(parts)


class StubDoctorArgs(DoctorArgs):
    """Minimal Doctor argument object for HC integration tests."""

    def __init__(self) -> None:
        self.only = None
        self.quick = False
        self.project = None
        self.json_output = False
        self.file = None
