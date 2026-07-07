"""Simulation persistence with verified readback.

Centralizes the conduct integration-simulation persistence contract:

1. Parse local verdict from raw Simulator output (CLEAN / GAPS FOUND)
2. Cross-check the body's attested epic ID against the CLI-passed epic ID
3. Persist via the in-process ``yoke_core.domain.epic.simulation_upsert``
4. Read back via ``yoke_core.domain.epic.simulation_get``
5. Verify persisted verdict matches local parse

CLI usage::

    echo "$simulator_output" | python3 -m yoke_core.domain.persist_simulation <epic-id> <phase>

Exit codes:
    0  = success; stdout contains CLEAN or GAPS FOUND
    10 = simulation-upsert failed
    11 = missing persisted row after upsert
    12 = inconclusive persisted verdict (empty verdict field)
    13 = parser mismatch (local verdict disagrees with persisted)
    14 = no local verdict parseable from Simulator output
    15 = verified simulation persisted but the Python-owned handoff failed
    16 = body's attested epic ID does not match the CLI-passed epic ID (wrong-epic body)
    17 = body has no extractable epic ID (no ``EPIC: YOK-N`` line and no heading fallback)
    2  = usage error (missing arguments or empty stdin)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import Optional

from yoke_core.domain import epic as _epic_domain
from yoke_core.domain.db_helpers import connect


# ---------------------------------------------------------------------------
# Parse result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulationParseResult:
    """Structured outcome of parsing Simulator output.

    Attributes:
        verdict: ``"CLEAN"``, ``"GAPS FOUND"``, or ``None`` if no verdict found.
        epic_id: Numeric epic ID extracted from the body, or ``None`` if absent.
        epic_id_source: ``"epic_line"`` if pulled from a ``EPIC: YOK-N`` line;
            ``"heading"`` if pulled from a ``# Simulation Report: YOK-N`` heading
            (legacy fallback); ``None`` if no epic ID was found.
    """

    verdict: Optional[str]
    epic_id: Optional[int]
    epic_id_source: Optional[str]


# Compile once. The ``EPIC:`` line is the canonical attestation; the heading
# is the legacy fallback that must keep working until every dispatch surface
# has been re-rendered.
_EPIC_LINE_RE = re.compile(r"^\s*EPIC:\s*YOK-(\d+)\s*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^#\s*Simulation Report:\s*YOK-(\d+)\b", re.MULTILINE)


# ---------------------------------------------------------------------------
# Verdict parsing
# ---------------------------------------------------------------------------

def parse_verdict(text: str) -> SimulationParseResult:
    """Extract the simulation verdict and attested epic ID from raw output.

    Returns a :class:`SimulationParseResult` populated from the body. The
    verdict matches conduct's inline parser vocabulary; the epic ID comes
    from the canonical ``EPIC: YOK-N`` line, falling back to the report
    heading for legacy bodies.
    """
    verdict: Optional[str]
    if "SIMULATION: CLEAN" in text:
        verdict = "CLEAN"
    elif "SIMULATION: GAPS FOUND" in text:
        verdict = "GAPS FOUND"
    elif "CLEAN" in text:
        verdict = "CLEAN"
    elif "GAPS FOUND" in text:
        verdict = "GAPS FOUND"
    else:
        verdict = None

    epic_match = _EPIC_LINE_RE.search(text)
    if epic_match:
        return SimulationParseResult(
            verdict=verdict,
            epic_id=int(epic_match.group(1)),
            epic_id_source="epic_line",
        )

    heading_match = _HEADING_RE.search(text)
    if heading_match:
        return SimulationParseResult(
            verdict=verdict,
            epic_id=int(heading_match.group(1)),
            epic_id_source="heading",
        )

    return SimulationParseResult(verdict=verdict, epic_id=None, epic_id_source=None)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def persist_and_verify(
    epic_id: str,
    phase: str,
    simulator_output: str,
) -> str:
    """Persist simulation output and verify readback.

    Returns the verified verdict string (``"CLEAN"`` or ``"GAPS FOUND"``).

    Raises:
        ``SystemExit(10)``  — upsert failed
        ``SystemExit(11)``  — missing persisted row
        ``SystemExit(12)``  — inconclusive verdict
        ``SystemExit(13)``  — parser mismatch
        ``SystemExit(14)``  — no parseable verdict in input
        ``SystemExit(15)``  — verified persist succeeded but auto-handoff failed
        ``SystemExit(16)``  — body's attested epic does not match CLI-passed epic
        ``SystemExit(17)``  — body has no extractable epic ID
        ``SystemExit(2)``   — empty input
    """
    if not simulator_output.strip():
        _err("No Simulator output provided.")
        raise SystemExit(2)

    parsed = parse_verdict(simulator_output)
    if parsed.verdict is None:
        _err("No parseable verdict in Simulator output (expected CLEAN or GAPS FOUND).")
        raise SystemExit(14)

    cli_epic_id = int(epic_id)

    if parsed.epic_id is None:
        _err(
            f"No epic ID attested in Simulator output for epic {cli_epic_id} phase {phase}. "
            f"Expected an `EPIC: YOK-{cli_epic_id}` line near the verdict, or a "
            f"`# Simulation Report: YOK-{cli_epic_id}` heading."
        )
        raise SystemExit(17)

    if parsed.epic_id != cli_epic_id:
        _err(
            f"Wrong-epic body for phase {phase}: CLI-passed epic was YOK-{cli_epic_id}, "
            f"but Simulator output attested epic YOK-{parsed.epic_id} "
            f"(source={parsed.epic_id_source}). Refusing to persist."
        )
        raise SystemExit(16)

    local_verdict = parsed.verdict

    with connect() as conn:
        try:
            _epic_domain.simulation_upsert(conn, epic_id, phase, simulator_output)
        except Exception as exc:
            _err(f"simulation-upsert failed for epic {epic_id} phase {phase}: {exc}")
            raise SystemExit(10)

        try:
            persisted_row = _epic_domain.simulation_get(conn, epic_id, phase)
        except LookupError:
            _err(
                f"No persisted simulation record found after upsert for "
                f"epic {epic_id} phase {phase}."
            )
            raise SystemExit(11)

    # simulation_get returns: id|epic_id|phase|result|body|created_at
    fields = persisted_row.split("|")
    persisted_verdict = fields[3] if len(fields) > 3 else ""

    if not persisted_verdict:
        _err(f"Persisted verdict is inconclusive for epic {epic_id} phase {phase}. "
             f"Local parse was '{local_verdict}'.")
        raise SystemExit(12)

    if persisted_verdict != local_verdict:
        _err(f"Parser mismatch for epic {epic_id} phase {phase}. "
             f"Local='{local_verdict}', persisted='{persisted_verdict}'.")
        raise SystemExit(13)

    if phase == "integration" and local_verdict == "CLEAN":
        from yoke_core.domain.conduct_reviewed_handoff import run as _handoff_run
        _handoff_rc = _handoff_run(int(epic_id))
        if _handoff_rc == 0:
            print(f"Auto-handoff: epic {epic_id} → reviewed-implementation "
                  f"(source=auto-transition:simulation)")
        elif _handoff_rc == 1:
            # Pre-condition not met (parent not at reviewing-implementation) —
            # expected when tasks are still in-flight. Not an error.
            pass
        else:
            _err(
                f"Auto-handoff failed for epic {epic_id} after verified simulation "
                f"persist (exit {_handoff_rc}). Partial success is not allowed."
            )
            raise SystemExit(15)

    return local_verdict


def _err(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="persist_simulation",
        description="Persist and verify epic simulation results",
    )
    parser.add_argument("epic_id", help="Epic ID")
    parser.add_argument("phase", help="Simulation phase (plan or integration)")

    args = parser.parse_args()

    if sys.stdin.isatty():
        _err("Simulator output must be piped to stdin.")
        return 2

    simulator_output = sys.stdin.read()

    try:
        verdict = persist_and_verify(args.epic_id, args.phase, simulator_output)
        print(verdict)
        return 0
    except SystemExit as e:
        return e.code  # type: ignore[return-value]


if __name__ == "__main__":
    sys.exit(main())
