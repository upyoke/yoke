"""Canonical simulation report headers and diagnosed validation failures."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

from yoke_contracts.public_ref import parse_public_item_ref

SimulationVerdict = Literal["CLEAN", "GAPS FOUND"]


class SimulationReportError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def parse_simulation_headers(
    body: str, public_ref: str | None = None
) -> SimulationVerdict:
    """Validate leading headers and all later standalone, unfenced headers."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    expected = f"EPIC: {public_ref}" if public_ref else "EPIC: <canonical public ref>"
    recovery = f"Start the report with SIMULATION: CLEAN or SIMULATION: GAPS FOUND, then {expected}."

    def refuse(code: str) -> None:
        raise SimulationReportError(code, f"{code}: {recovery}")

    if not lines or not lines[0].startswith("SIMULATION:"):
        refuse("simulation_identity_missing")
    verdict = lines[0].removeprefix("SIMULATION: ")
    if lines[0] not in ("SIMULATION: CLEAN", "SIMULATION: GAPS FOUND"):
        refuse("simulation_verdict_invalid")
    if len(lines) < 2 or not lines[1].startswith("EPIC: "):
        refuse("simulation_identity_missing")
    identity = lines[1].removeprefix("EPIC: ")
    prefix, sequence = parse_public_item_ref(identity)
    if prefix is None or sequence is None or sequence < 1:
        refuse("simulation_identity_mismatch")
    if public_ref is not None and identity != public_ref:
        refuse("simulation_identity_mismatch")
    fence: tuple[str, int] | None = None
    for line in lines[2:]:
        match = re.match(r"^(`{3,}|~{3,})(.*)$", line)
        if match:
            marker, suffix = match.groups()
            if fence is None:
                fence = (marker[0], len(marker))
            elif (
                marker[0] == fence[0] and len(marker) >= fence[1] and not suffix.strip()
            ):
                fence = None
            continue
        if fence is not None:
            continue
        if line.startswith("SIMULATION:") and line != f"SIMULATION: {verdict}":
            refuse("simulation_verdict_invalid")
        if line.startswith("EPIC:") and line != f"EPIC: {identity}":
            refuse("simulation_identity_mismatch")
    return cast(SimulationVerdict, verdict)


@dataclass(frozen=True)
class SimulationReceipt:
    public_ref: str
    phase: str
    requirement_id: int
    run_id: int
    verdict: SimulationVerdict
    verified: bool = True

    @property
    def message(self) -> str:
        return f"{self.public_ref} simulation {self.phase} {self.verdict}; run {self.run_id} verified"
