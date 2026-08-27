"""User-equivalence probes declared alongside one captured golden baseline.

A restored home is provably the captured one, but structure is not liveness: a
credential file can come back byte-identical and still hold an expired token.
The probes close that gap, and they live beside the golden rather than in this
engine because which programs must report themselves signed in is a fact about
one machine's baseline, not about every project Yoke serves. Recapturing a
baseline with a new tool updates its probes in the same motion.

A probe answers one of three ways, and the runner keeps them apart because
their recoveries differ. The program reported itself signed in; the program ran
and did not; or the bridge never delivered the probe, so the program has said
nothing at all. Only the second is a fact about the golden. Collapsing the
third into it sends an operator to recapture a whole home over a host defect
that would fail again on the next restore.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
from typing import Any, Callable, Sequence

from yoke_harness.ssh_mac_gui_session import (
    MacosSessionContextFailure,
    classify_macos_session_context_failure,
)
from yoke_harness.test_machine_types import HostActionResult


PROBE_LIMIT = 20
PROBE_ARGUMENT_LIMIT = 24
PROBE_TIMEOUT_SECONDS = 120

NO_VERDICT_ERROR_CODE = "baseline_probe_bridge_unavailable"
FAILED_ERROR_CODE = "baseline_probe_failed"

BRIDGE_CALL_RAISED_CAUSE = "bridge_call_raised"
BRIDGE_CALL_RAISED_REASON = "the GUI-session bridge could not be called at all"
NOT_SIGNED_IN_CAUSE = "probe_reported_not_signed_in"
NOT_SIGNED_IN_REASON = "the probe ran and its program did not report itself signed in"
NOT_SIGNED_IN_RECOVERY = (
    "recapture the golden from a session where the program is signed in, or "
    "correct the probe argv or expectation in the document beside the golden"
)
_RECOVERY_BY_CAUSE = {
    BRIDGE_CALL_RAISED_CAUSE: (
        "check SSH reachability and Terminal.app control on the host, then "
        "re-run `yoke test-machine verify`"
    ),
    "macos_gui_session_context_unavailable": (
        "repair the Terminal.app bridge on the host and re-run "
        "`yoke test-machine verify`; the probe never reached its program"
    ),
    "macos_gui_audit_session_unavailable": (
        "run the probe from the logged-in GUI session; this one had no "
        "audit-session context to switch into"
    ),
    "macos_window_server_context_unavailable": (
        "run the probe from the logged-in GUI session; this one had no "
        "window-server context"
    ),
    "macos_login_keychain_context_unavailable": (
        "recapture the golden from a login session where the program is "
        "signed in; its credential is present but not readable here"
    ),
}


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


def _failed_row(
    probe: BaselineProbe,
    *,
    exit_code: int | None,
    expectation_met: bool,
    cause: str,
    reason: str,
) -> dict[str, Any]:
    """Record one failure as a cause an operator can act on."""
    return {
        "name": probe.name,
        "ok": False,
        "exit_code": exit_code,
        "expectation_met": expectation_met,
        "outcome": "failed",
        "cause": cause,
        "reason": reason,
        "recovery": _RECOVERY_BY_CAUSE.get(cause, NOT_SIGNED_IN_RECOVERY),
    }


def _is_undelivered(classified: MacosSessionContextFailure | None) -> bool:
    """True when the bridge itself failed, so no program verdict was reached."""
    return (
        classified is not None
        and classified.error_code == "macos_gui_session_context_unavailable"
    )


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
    evidence. A failure is therefore explained by a classified cause, reason,
    and recovery drawn from fixed text, never by the output itself.

    A failing probe and an undelivered one are different answers. The bridge
    reports its own failure as an exit code on a synthetic result rather than
    by raising, so a bridge that never reached the program looks exactly like a
    program reporting itself signed out unless the result is classified. The
    two close under different error codes because they have different
    recoveries: repair the host, or recapture the golden.
    """
    rows: list[dict[str, Any]] = []
    for probe in probes:
        try:
            result = run_gui_command(
                list(probe.argv),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except Exception:
            rows.append(
                _failed_row(
                    probe,
                    exit_code=None,
                    expectation_met=False,
                    cause=BRIDGE_CALL_RAISED_CAUSE,
                    reason=BRIDGE_CALL_RAISED_REASON,
                )
            )
            return HostActionResult(False, {"probes": rows}, NO_VERDICT_ERROR_CODE)
        exit_code = int(result.returncode)
        expectation = probe.expect_output_contains
        matched = expectation is None or expectation in "\n".join(
            (result.stdout or "", result.stderr or "")
        )
        if exit_code == 0 and matched:
            rows.append(
                {
                    "name": probe.name,
                    "ok": True,
                    "exit_code": exit_code,
                    "expectation_met": matched,
                    "outcome": "passed",
                }
            )
            continue
        classified = classify_macos_session_context_failure(result)
        rows.append(
            _failed_row(
                probe,
                exit_code=exit_code,
                expectation_met=matched,
                cause=(
                    classified.error_code
                    if classified is not None
                    else NOT_SIGNED_IN_CAUSE
                ),
                reason=(
                    classified.reason
                    if classified is not None
                    else NOT_SIGNED_IN_REASON
                ),
            )
        )
        return HostActionResult(
            False,
            {"probes": rows},
            NO_VERDICT_ERROR_CODE if _is_undelivered(classified) else FAILED_ERROR_CODE,
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
    "FAILED_ERROR_CODE",
    "NO_VERDICT_ERROR_CODE",
    "PROBE_ARGUMENT_LIMIT",
    "PROBE_LIMIT",
    "PROBE_TIMEOUT_SECONDS",
    "BaselineProbe",
    "BaselineProbeError",
    "parse_baseline_probes",
    "reach_user_equivalent_baseline",
    "run_baseline_probes",
]
