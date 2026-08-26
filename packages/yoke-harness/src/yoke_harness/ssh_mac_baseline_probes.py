"""User-equivalence probes declared alongside one captured golden baseline.

A restored home is provably the captured one, but structure is not liveness: a
credential file can come back byte-identical and still hold an expired token.
The probes close that gap, and they live beside the golden rather than in this
engine because which programs must report themselves signed in is a fact about
one machine's baseline, not about every project Yoke serves. Recapturing a
baseline with a new tool updates its probes in the same motion.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
from typing import Any, Callable, Sequence

from yoke_harness.test_machine_types import HostActionResult


PROBE_LIMIT = 20
PROBE_ARGUMENT_LIMIT = 24
PROBE_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class BaselineProbe:
    """One bounded, argv-shaped assertion about the restored host."""

    name: str
    argv: tuple[str, ...]
    expect_output_contains: str | None


class BaselineProbeError(ValueError):
    """The declared probe document is missing or not a bounded argv contract."""


def _text(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise BaselineProbeError(f"probe {field} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise BaselineProbeError(f"probe {field} is empty or too long")
    return normalized


def parse_baseline_probes(document: str) -> tuple[BaselineProbe, ...]:
    """Validate one probe document into bounded argv, or refuse it."""
    try:
        payload = json.loads(document)
    except (TypeError, ValueError) as exc:
        raise BaselineProbeError("probe document is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"probes"}:
        raise BaselineProbeError("probe document must be an object with probes")
    declared = payload["probes"]
    if not isinstance(declared, list) or not 1 <= len(declared) <= PROBE_LIMIT:
        raise BaselineProbeError(
            f"probe document must declare 1 to {PROBE_LIMIT} probes"
        )
    probes: list[BaselineProbe] = []
    for entry in declared:
        if not isinstance(entry, dict) or not set(entry) <= {
            "name",
            "argv",
            "expect_output_contains",
        }:
            raise BaselineProbeError("probe entries carry name, argv, expectation")
        argv = entry.get("argv")
        if (
            not isinstance(argv, list)
            or not 1 <= len(argv) <= PROBE_ARGUMENT_LIMIT
            or any(not isinstance(value, str) or not value for value in argv)
        ):
            raise BaselineProbeError("probe argv must be 1 to 24 non-empty strings")
        program = PurePosixPath(argv[0])
        if not program.is_absolute() or ".." in program.parts:
            raise BaselineProbeError("probe argv must name an absolute program")
        expectation = entry.get("expect_output_contains")
        probes.append(
            BaselineProbe(
                name=_text(entry.get("name"), field="name", limit=80),
                argv=tuple(argv),
                expect_output_contains=(
                    None
                    if expectation is None
                    else _text(
                        expectation,
                        field="expect_output_contains",
                        limit=200,
                    )
                ),
            )
        )
    return tuple(probes)


def run_baseline_probes(
    probes: Sequence[BaselineProbe],
    *,
    run_gui_command: Callable[..., Any],
) -> HostActionResult:
    """Run every probe in the logged-in GUI session and close the outcome.

    Probes run through the GUI bridge because an SSH session cannot reach the
    login keychain, and a keychain-backed program answering from the wrong
    session reports expired credentials whose files are perfectly intact.

    Probe output is summarized rather than recorded: a signed-in report names
    the account it is signed in as, and that identity has no business in QA
    evidence.
    """
    rows: list[dict[str, Any]] = []
    for probe in probes:
        try:
            result = run_gui_command(
                list(probe.argv),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except Exception:
            rows.append({"name": probe.name, "ok": False, "outcome": "unavailable"})
            return HostActionResult(
                False,
                {"probes": rows},
                "baseline_probe_unavailable",
            )
        exit_code = int(result.returncode)
        expectation = probe.expect_output_contains
        matched = expectation is None or expectation in "\n".join(
            (result.stdout or "", result.stderr or "")
        )
        ok = exit_code == 0 and matched
        rows.append(
            {
                "name": probe.name,
                "ok": ok,
                "exit_code": exit_code,
                "expectation_met": matched,
                "outcome": "passed" if ok else "failed",
            }
        )
        if not ok:
            return HostActionResult(
                False,
                {"probes": rows},
                "baseline_probe_failed",
            )
    return HostActionResult(True, {"probes": rows})


def reach_user_equivalent_baseline(control: Any) -> HostActionResult:
    """Restore the declared baseline, then prove the restored host works.

    One composition for both baseline entry points, so the restore and its
    proof cannot drift apart depending on which caller reached them.
    """
    restored = control.reset_installer_test_host()
    if not restored.ok:
        return restored
    proven = control.prove_user_equivalent()
    return HostActionResult(
        proven.ok,
        {**restored.evidence, "user_equivalence": proven.evidence},
        proven.error_code,
    )


__all__ = [
    "PROBE_ARGUMENT_LIMIT",
    "PROBE_LIMIT",
    "PROBE_TIMEOUT_SECONDS",
    "BaselineProbe",
    "BaselineProbeError",
    "parse_baseline_probes",
    "reach_user_equivalent_baseline",
    "run_baseline_probes",
]
