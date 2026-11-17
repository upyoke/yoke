"""Upload, execute, and read the receipt of one golden-baseline capture."""

from __future__ import annotations

import hashlib
import shlex
from pathlib import PurePosixPath
from typing import Any, Protocol

from yoke_contracts.machine_qa_failures import (
    HostControlLocalError,
    bounded_machine_qa_diagnostic,
)
from yoke_cli.config.path_doctor import (
    PathStateContract,
    resolve_path_state_contract,
)

from yoke_harness.ssh_mac_baseline_probes import (
    prove_probes_document,
)
from yoke_harness.ssh_mac_full_reset import is_safe_test_mac_home
from yoke_contracts.ssh_mac_full_reset_contract import (
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
from yoke_harness.ssh_mac_sign_in_apps import quit_sign_in_apps
from yoke_contracts.test_machine_types import HostActionResult


class CaptureCommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


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
    selected_path_state = path_state or resolve_path_state_contract(target="posix",
        env={"HOME": home, "SHELL": "/bin/zsh"}
