"""The harness CLI versions a Test Machine golden restores, recorded beside it.

Capture probes each harness CLI's ``--version`` as the test user and writes
the versions to ``<golden>.harness-clis``. A refresh reads that record to
decide whether the golden is behind the published releases, installs the
newer releases with each vendor's installer, and captures a new golden.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from yoke_contracts.harness_cli_releases import (
    HARNESS_CLI_RELEASE_BY_ID,
    HARNESS_CLI_RELEASES,
    VERSION_TOKEN_PATTERN,
    outdated_harness_clis,
)
from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT
from yoke_harness.harness_cli_install_program import HOST_PROGRAM
from yoke_harness.test_machine_types import HostActionResult

GOLDEN_HARNESS_CLIS_SUFFIX = ".harness-clis"
VERSION_PROBE_TIMEOUT_SECONDS = 120
INSTALL_TIMEOUT_SECONDS = 600
PROVISIONING_DOC = "docs/packs/machine-qa/host-provisioning.md"


def _host_program(control: Any, action: str, payload: Any, timeout: int) -> Any:
    gui = getattr(control, "os", None) == "macos"
    result = control.run_command(
        [
            "/usr/bin/python3",
            "-c",
            HOST_PROGRAM,
            VERSION_TOKEN_PATTERN,
            action,
            json.dumps(payload),
        ],
        timeout=timeout,
        **({"required_session_context": GUI_SESSION_CONTEXT} if gui else {}),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"harness_cli_{action}_failed: {payload[0] if action == 'install' else 'probe'} "
            f"host exit {result.returncode}: "
            f"{result.stderr.strip()[:400]}; repair the test user's CLI installation "
            "and /usr/bin/python3, then rerun the QA plan"
        )
    lines = result.stdout.strip().splitlines()
    return json.loads(lines[-1] if lines else "")


def probe_harness_cli_versions(control: Any) -> dict[str, dict[str, Any]]:
    """Return versions and unreadable CLI exit codes/stderr, in macOS GUI context."""
    return _host_program(
        control,
        "probe",
        [[r.harness_id, list(r.executables)] for r in HARNESS_CLI_RELEASES],
        VERSION_PROBE_TIMEOUT_SECONDS,
    )


def record_golden_harness_clis(control: Any, destination: str) -> HostActionResult:
    """Write the live harness CLI versions beside a just-captured golden."""
    sidecar = destination + GOLDEN_HARNESS_CLIS_SUFFIX
    try:
        probes = probe_harness_cli_versions(control)
        versions = {h: p["version"] for h, p in probes.items()}
    except (RuntimeError, ValueError) as error:
        return HostActionResult(
            False,
            {"path": sidecar, "detail": str(error)},
            "golden_harness_clis_probe_failed",
        )
    missing = sorted(harness for harness, version in versions.items() if not version)
    if missing:
        return HostActionResult(
            False,
            {
                "path": sidecar,
                "harness_cli_versions": versions,
                "probes": {h: probes[h] for h in missing},
                "recovery": (
                    "Install and sign in " + ", ".join(missing) + " as the test "
                    f"user following {PROVISIONING_DOC}, then capture to a new "
                    "destination; do not register this capture."
                ),
            },
            "golden_harness_cli_version_unreadable",
        )
    try:
        control.upload_remote_text(sidecar, json.dumps(versions, sort_keys=True))
    except Exception as error:  # every transport names its own write failure
        return HostActionResult(
            False,
            {
                "path": sidecar,
                "detail": str(error),
                "recovery": "Repair write access beside the golden, then capture "
                "to a new destination; do not register this capture.",
            },
            "golden_harness_clis_write_failed",
        )
    return HostActionResult(True, {"harness_cli_versions": versions})


def read_golden_harness_clis(control: Any, golden: str) -> dict[str, str] | None:
    """Return the versions recorded beside *golden*, or None when unrecorded."""
    text = control.read_remote_text(golden + GOLDEN_HARNESS_CLIS_SUFFIX)
    if not text:
        return None
    recorded = json.loads(text)
    return {str(key): str(value) for key, value in recorded.items() if value}


def install_harness_clis(
    control: Any, latest: Mapping[str, str], harness_ids: Sequence[str]
) -> HostActionResult:
    """Install each named harness CLI's latest release and prove the version."""
    installs = []
    held_back = []
    observed = {}
    for harness_id in harness_ids:
        release = HARNESS_CLI_RELEASE_BY_ID[harness_id]
        receipt = _host_program(
            control,
            "install",
            [
                harness_id,
                list(release.executables),
                release.install_script,
                latest[harness_id],
            ],
            INSTALL_TIMEOUT_SECONDS,
        )
        probe = receipt["probe"]
        observed[harness_id] = probe["version"]
        diagnostic = receipt.get("failed_probe", probe)
        detail = (
            f"{harness_id} {latest[harness_id]} exit {diagnostic['exit_code']}: "
            f"{diagnostic['stderr']}"
        )
        installs.append({"harness_id": harness_id, **receipt})
        if receipt.get("held_back"):
            held_back.append(
                f"held back: {harness_id} {latest[harness_id]} does not run on "
                f"this host: {diagnostic['stderr']} (exit {diagnostic['exit_code']}); "
                f"using {probe['version']}"
            )
        failed_install = receipt["install_exit_code"] != 0
        if failed_install:
            detail = (
                f"{harness_id} {latest[harness_id]} installer exit "
                f"{receipt['install_exit_code']}: {receipt['install_stderr']}"
            )
        behind = harness_id in outdated_harness_clis(observed, latest)
        if failed_install or (behind and not receipt.get("held_back")):
            return HostActionResult(
                False,
                {
                    "detail": detail,
                    "installs": installs,
                    "held_back": held_back,
                    "recovery": f"Repair {harness_id} as the test user following "
                    f"{PROVISIONING_DOC}, prove --version runs, then rerun the QA plan. "
                    + receipt["install_stderr"],
                },
                "harness_cli_install_failed"
                if failed_install
                else "harness_cli_install_unverified",
            )
    return HostActionResult(
        True,
        {
            "held_back": held_back,
            "installs": installs,
            "harness_cli_versions": observed,
        },
    )


__all__ = [
    "GOLDEN_HARNESS_CLIS_SUFFIX",
    "install_harness_clis",
    "probe_harness_cli_versions",
    "read_golden_harness_clis",
    "record_golden_harness_clis",
]
