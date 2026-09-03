"""Upload, execute, and read the receipt of one golden-baseline capture."""

from __future__ import annotations

import hashlib
import shlex
from typing import Any, Protocol

from yoke_cli.config.path_doctor import (
    PathStateContract,
    resolve_path_state_contract,
)

from yoke_harness.ssh_mac_baseline_probes import (
    prove_probes_document,
    read_declared_probes_document,
)
from yoke_harness.ssh_mac_full_reset import is_safe_test_mac_home
from yoke_harness.ssh_mac_full_reset_contract import (
    GOLDEN_MANIFEST_SUFFIX,
    GOLDEN_PROBES_SUFFIX,
    golden_baseline_clears_home,
    resolve_full_reset_path_contract,
)
from yoke_harness.ssh_mac_golden_capture_contract import (
    GOLDEN_CAPTURE_REMOTE_PATH,
    GOLDEN_SIDECAR_MODE,
)
from yoke_harness.ssh_mac_golden_capture_receipt import (
    capture_failure_outcome,
    closed_capture_outcomes,
)
from yoke_harness.ssh_mac_golden_capture_script import render_golden_capture_script
from yoke_harness.test_machine_types import HostActionResult


class CaptureCommandResult(Protocol):
    returncode: int
    stdout: str


class CaptureRunner(Protocol):
    def __call__(
        self,
        command: str,
        *,
        timeout: int = 60,
    ) -> CaptureCommandResult: ...


class CaptureUploader(Protocol):
    def __call__(self, path: str, content: str) -> None: ...


#: A whole-home copy on a spinning-disk Mac is the longest single command the
#: product runs against a test host.
CAPTURE_TIMEOUT_SECONDS = 3600


def probes_document_digest(document: str) -> str:
    """Return the digest the manifest records for the sealed probes."""
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def execute_golden_capture(
    *,
    run_remote: CaptureRunner,
    upload_text: CaptureUploader,
    home: str,
    destination: str,
    probes_document: str,
    path_state: PathStateContract | None = None,
) -> HostActionResult:
    """Copy one host's home to *destination* and seal its sidecars.

    The probes travel with the baseline they describe: sealing them beside the
    golden is what makes a later restore provable, and a golden captured
    without them is one no reset can accept.
    """
    if not is_safe_test_mac_home(home):
        return HostActionResult(
            False, {"destination": destination}, "unsafe_test_mac_home"
        )
    if not golden_baseline_clears_home(destination, home=home):
        return HostActionResult(
            False,
            {"destination": destination},
            "golden_destination_unsafe",
        )
    selected_path_state = path_state or resolve_path_state_contract(
        env={"HOME": home, "SHELL": "/bin/zsh"}
    )
    if selected_path_state.home != home:
        return HostActionResult(
            False,
            {"destination": destination},
            "test_mac_path_home_mismatch",
        )
    try:
        capture_contract = resolve_full_reset_path_contract(selected_path_state)
    except ValueError:
        return HostActionResult(
            False,
            {"destination": destination},
            "unsafe_test_mac_tool_path",
        )
    digest = probes_document_digest(probes_document)

    error_code = "golden_capture_failed"
    outcomes: dict[str, str | int] | None = None
    refusal: dict[str, str] | None = None
    phase: str | None = None
    try:
        preclean = run_remote(
            shlex.join(["/bin/rm", "-f", "--", GOLDEN_CAPTURE_REMOTE_PATH]),
        )
        if int(preclean.returncode) != 0:
            error_code = "golden_capture_script_preclean_failed"
        else:
            upload_text(
                GOLDEN_CAPTURE_REMOTE_PATH,
                render_golden_capture_script(capture_contract),
            )
            mode = run_remote(
                shlex.join(["/bin/chmod", "0700", GOLDEN_CAPTURE_REMOTE_PATH]),
            )
            if int(mode.returncode) != 0:
                error_code = "golden_capture_script_mode_failed"
            else:
                result = run_remote(
                    shlex.join([GOLDEN_CAPTURE_REMOTE_PATH, home, destination, digest]),
                    timeout=CAPTURE_TIMEOUT_SECONDS,
                )
                if int(result.returncode) == 0:
                    outcomes = closed_capture_outcomes(str(result.stdout))
                    if outcomes is None:
                        error_code = "golden_capture_output_invalid"
                else:
                    parsed = capture_failure_outcome(str(result.stdout))
                    if parsed is not None:
                        phase, refusal = parsed
                        error_code = (
                            f"golden_capture_{refusal['reason']}"
                            if refusal
                            else f"golden_capture_{phase}_failed"
                        )
    except Exception:
        error_code = "golden_capture_adapter_failed"

    cleanup = _remove_capture_script(run_remote)
    if outcomes is None or not cleanup:
        evidence: dict[str, object] = {
            "destination": destination,
            "paths": [
                {"path": destination, "outcome": "not-captured"},
                {
                    "path": GOLDEN_CAPTURE_REMOTE_PATH,
                    "outcome": "removed" if cleanup else "cleanup-failed",
                },
            ],
        }
        if phase is not None:
            evidence["capture_phase"] = phase
        if refusal is not None:
            evidence["refusal"] = refusal
        return HostActionResult(
            False,
            evidence,
            error_code if cleanup else "golden_capture_script_cleanup_failed",
        )

    sealed = _seal_probes_document(
        run_remote,
        upload_text,
        destination=destination,
        document=probes_document,
    )
    if not sealed:
        return HostActionResult(
            False,
            {
                "destination": destination,
                "paths": [
                    {"path": destination, "outcome": "captured"},
                    {
                        "path": destination + GOLDEN_PROBES_SUFFIX,
                        "outcome": "not-sealed",
                    },
                ],
            },
            "golden_probes_seal_failed",
        )
    return HostActionResult(
        True,
        {
            "destination": destination,
            "source_home": home,
            "captured_entries": outcomes["captured_entries"],
            "captured_kilobytes": outcomes["captured_kilobytes"],
            "manifest_digest": outcomes["manifest_digest"],
            "probes_digest": digest,
            "paths": [
                {"path": destination, "outcome": "captured"},
                {
                    "path": destination + GOLDEN_MANIFEST_SUFFIX,
                    "outcome": "sealed",
                },
                {
                    "path": destination + GOLDEN_PROBES_SUFFIX,
                    "outcome": "sealed",
                },
                {"path": GOLDEN_CAPTURE_REMOTE_PATH, "outcome": "removed"},
            ],
        },
    )


def _remove_capture_script(run_remote: CaptureRunner) -> bool:
    try:
        cleanup = run_remote(
            shlex.join(["/bin/rm", "-f", "--", GOLDEN_CAPTURE_REMOTE_PATH]),
        )
    except Exception:
        return False
    return int(cleanup.returncode) == 0


def _seal_probes_document(
    run_remote: CaptureRunner,
    upload_text: CaptureUploader,
    *,
    destination: str,
    document: str,
) -> bool:
    sidecar = destination + GOLDEN_PROBES_SUFFIX
    try:
        upload_text(sidecar, document)
        sealed = run_remote(
            shlex.join(["/bin/chmod", GOLDEN_SIDECAR_MODE, "--", sidecar]),
        )
    except Exception:
        return False
    return int(sealed.returncode) == 0


def capture_golden_baseline(
    control: Any,
    *,
    destination: str,
    probes_document: str | None = None,
) -> HostActionResult:
    """Prove the host is capture-ready, then copy its home to *destination*.

    The probes run first and must all pass. A capture taken while a declared
    program is signed out produces a baseline that every later reset restores
    and then rejects as not user-equivalent, so the machine could never pass
    again.
    """
    document = probes_document
    if document is None:
        document = read_declared_probes_document(control)
    if document is None:
        return HostActionResult(
            False,
            {"destination": destination, "probes": [], "declared": False},
            "baseline_probes_not_declared",
        )
    proven = prove_probes_document(control, document)
    if not proven.ok:
        return HostActionResult(
            False,
            {"destination": destination, "user_equivalence": proven.evidence},
            proven.error_code,
        )
    captured = execute_golden_capture(
        run_remote=control.run_remote_command,
        upload_text=control.upload_remote_text,
        home=control.home,
        destination=destination,
        probes_document=document,
        path_state=control.path_state,
    )
    if not captured.ok:
        return captured
    return HostActionResult(
        True,
        {**captured.evidence, "user_equivalence": proven.evidence},
    )


__all__ = [
    "CAPTURE_TIMEOUT_SECONDS",
    "capture_golden_baseline",
    "execute_golden_capture",
    "probes_document_digest",
]
