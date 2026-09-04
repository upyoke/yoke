"""Driver coverage for capturing one macOS host's golden baseline."""

from __future__ import annotations

import shlex
from types import SimpleNamespace

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    run_zsh_syntax_if_available,
)
from yoke_harness.ssh_mac_golden_capture import (
    execute_golden_capture,
    probes_document_digest,
)
from yoke_harness.ssh_mac_golden_capture_contract import (
    CAPTURE_ENTRIES_PREFIX,
    CAPTURE_FAILURE_PREFIX,
    CAPTURE_KILOBYTES_PREFIX,
    CAPTURE_MANIFEST_DIGEST_PREFIX,
    CAPTURE_PHASES,
    CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED,
    CAPTURE_REFUSAL_KIND_FOREIGN_OWNER,
    CAPTURE_REFUSAL_KIND_RESIDUE,
    CAPTURE_REFUSAL_PREFIX,
    GOLDEN_CAPTURE_MARKER,
    GOLDEN_CAPTURE_REMOTE_PATH,
    GOLDEN_SIDECAR_MODE,
)
from yoke_harness.ssh_mac_golden_capture_script import render_golden_capture_script
from yoke_harness.ssh_mac_full_reset_contract import (
    GOLDEN_MANIFEST_SUFFIX,
    GOLDEN_PROBES_SUFFIX,
    resolve_full_reset_path_contract,
)
from yoke_cli.config.path_doctor import resolve_path_state_contract


HOME = "/Users/tester"
DESTINATION = "/Users/Shared/yoke-golden/tester-home-20260903"
PROBES = '{"probes": [{"name": "harness", "argv": ["/bin/test", "-e", "/"]}]}'
MANIFEST_DIGEST = "c" * 64


class FakeCaptureTransport:
    def __init__(self, stdout: str, *, capture_returncode: int = 0) -> None:
        self.stdout = stdout
        self.capture_returncode = capture_returncode
        self.uploads: dict[str, str] = {}
        self.commands: list[tuple[str, int]] = []
        self.cleanup_returncode = 0
        self.seal_returncode = 0

    def upload(self, path: str, content: str) -> None:
        self.uploads[path] = content

    def run(self, command: str, *, timeout: int = 60):
        self.commands.append((command, timeout))
        argv = shlex.split(command)
        if argv and argv[0] == GOLDEN_CAPTURE_REMOTE_PATH:
            return SimpleNamespace(
                returncode=self.capture_returncode,
                stdout=self.stdout,
            )
        if argv[:3] == ["/bin/rm", "-f", "--"]:
            return SimpleNamespace(returncode=self.cleanup_returncode, stdout="")
        if argv[:2] == ["/bin/chmod", GOLDEN_SIDECAR_MODE]:
            return SimpleNamespace(returncode=self.seal_returncode, stdout="")
        return SimpleNamespace(returncode=0, stdout="")


def closed_capture_stdout(
    *,
    entries: int = 34,
    kilobytes: int = 2048,
    manifest_digest: str = MANIFEST_DIGEST,
) -> str:
    """Return the counted success receipt the capture parser accepts."""
    return "\n".join(
        (
            f"{CAPTURE_ENTRIES_PREFIX}{entries}",
            f"{CAPTURE_KILOBYTES_PREFIX}{kilobytes}",
            f"{CAPTURE_MANIFEST_DIGEST_PREFIX}{manifest_digest}",
            GOLDEN_CAPTURE_MARKER,
        )
    )


def refusal_stdout(phase: str, kind: str, path: str) -> str:
    return "\n".join(
        (
            f"{CAPTURE_FAILURE_PREFIX}{CAPTURE_PHASES[phase]}",
            f"{CAPTURE_REFUSAL_PREFIX}{kind} {path}",
        )
    )


def _capture(transport: FakeCaptureTransport, **overrides):
    arguments = {
        "run_remote": transport.run,
        "upload_text": transport.upload,
        "home": HOME,
        "destination": DESTINATION,
        "probes_document": PROBES,
    }
    arguments.update(overrides)
    return execute_golden_capture(**arguments)


@pytest.mark.parametrize(
    "home",
    ["", "/", "~", "$HOME", "/Users", "/Users/shared", "/Users/a/b"],
)
def test_capture_rejects_any_non_explicit_dedicated_mac_home(home: str) -> None:
    transport = FakeCaptureTransport(closed_capture_stdout())

    result = _capture(transport, home=home)

    assert not result.ok
    assert result.error_code == "unsafe_test_mac_home"
    assert transport.commands == []


@pytest.mark.parametrize(
    "destination",
    [HOME, f"{HOME}/golden", "relative/path", "/Users/../etc"],
)
def test_capture_rejects_a_destination_its_own_reset_would_destroy(
    destination: str,
) -> None:
    # A baseline stored inside the home is erased by the reset it drives.
    transport = FakeCaptureTransport(closed_capture_stdout())

    result = _capture(transport, destination=destination)

    assert not result.ok
    assert result.error_code == "golden_destination_unsafe"
    assert transport.commands == []


def test_a_successful_capture_seals_both_sidecars_and_reports_what_it_wrote() -> None:
    transport = FakeCaptureTransport(closed_capture_stdout())

    result = _capture(transport)

    assert result.ok, result.error_code
    assert result.evidence["destination"] == DESTINATION
    assert result.evidence["captured_entries"] == 34
    assert result.evidence["manifest_digest"] == MANIFEST_DIGEST
    assert result.evidence["probes_digest"] == probes_document_digest(PROBES)
    outcomes = {row["path"]: row["outcome"] for row in result.evidence["paths"]}
    assert outcomes[DESTINATION] == "captured"
    assert outcomes[DESTINATION + GOLDEN_MANIFEST_SUFFIX] == "sealed"
    assert outcomes[DESTINATION + GOLDEN_PROBES_SUFFIX] == "sealed"
    assert outcomes[GOLDEN_CAPTURE_REMOTE_PATH] == "removed"
    # The probes travel with the baseline they describe.
    assert transport.uploads[DESTINATION + GOLDEN_PROBES_SUFFIX] == PROBES
    assert any(
        argv[:2] == ["/bin/chmod", GOLDEN_SIDECAR_MODE]
        for argv in (shlex.split(command) for command, _timeout in transport.commands)
    )


def test_the_capture_program_receives_the_home_destination_and_probe_digest() -> None:
    transport = FakeCaptureTransport(closed_capture_stdout())

    _capture(transport)

    invocation = next(
        shlex.split(command)
        for command, _timeout in transport.commands
        if command.startswith(GOLDEN_CAPTURE_REMOTE_PATH)
    )
    assert invocation == [
        GOLDEN_CAPTURE_REMOTE_PATH,
        HOME,
        DESTINATION,
        probes_document_digest(PROBES),
    ]


@pytest.mark.parametrize(
    ("phase", "kind", "path", "error_code"),
    [
        (
            "assert_no_yoke_residue",
            CAPTURE_REFUSAL_KIND_RESIDUE,
            f"{HOME}/.yoke",
            "golden_capture_yoke_residue",
        ),
        (
            "assert_home_ownership",
            CAPTURE_REFUSAL_KIND_FOREIGN_OWNER,
            f"{HOME}/Library/root-owned",
            "golden_capture_foreign_owner",
        ),
        (
            "validate_destination",
            CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED,
            DESTINATION,
            "golden_capture_destination_occupied",
        ),
    ],
)
def test_a_refusal_names_the_path_and_what_to_change(
    phase: str,
    kind: str,
    path: str,
    error_code: str,
) -> None:
    transport = FakeCaptureTransport(
        refusal_stdout(phase, kind, path),
        capture_returncode=1,
    )

    result = _capture(transport)

    assert not result.ok
    assert result.error_code == error_code
    assert result.evidence["capture_phase"] == phase
    assert result.evidence["refusal"]["path"] == path
    assert path in result.evidence["refusal"]["recovery"]
    # Nothing was sealed beside a baseline that was never written.
    assert transport.uploads.get(DESTINATION + GOLDEN_PROBES_SUFFIX) is None


def test_a_capture_whose_probes_never_seal_reports_the_unsealed_sidecar() -> None:
    transport = FakeCaptureTransport(closed_capture_stdout())
    transport.seal_returncode = 1

    result = _capture(transport)

    assert not result.ok
    assert result.error_code == "golden_probes_seal_failed"
    outcomes = {row["path"]: row["outcome"] for row in result.evidence["paths"]}
    assert outcomes[DESTINATION + GOLDEN_PROBES_SUFFIX] == "not-sealed"


def test_an_unparseable_receipt_is_not_a_successful_capture() -> None:
    transport = FakeCaptureTransport("captured everything, honest\n")

    result = _capture(transport)

    assert not result.ok
    assert result.error_code == "golden_capture_output_invalid"


def test_the_capture_program_is_valid_zsh() -> None:
    script = render_golden_capture_script(
        resolve_full_reset_path_contract(
            resolve_path_state_contract(env={"HOME": HOME, "SHELL": "/bin/zsh"})
        )
    )

    checked = run_zsh_syntax_if_available(script)

    if checked is None:
        pytest.skip("zsh is required to syntax-check the macOS capture program")
    assert checked.returncode == 0, checked.stderr
