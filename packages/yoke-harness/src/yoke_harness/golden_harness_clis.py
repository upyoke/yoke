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
from yoke_harness.test_machine_types import HostActionResult

GOLDEN_HARNESS_CLIS_SUFFIX = ".harness-clis"
VERSION_PROBE_TIMEOUT_SECONDS = 120
INSTALL_TIMEOUT_SECONDS = 600
PROVISIONING_DOC = "docs/packs/machine-qa/host-provisioning.md"

# Runs on the host as the test user; only versions leave it.
_VERSION_PROGRAM = """
import json, os, re, shutil, subprocess, sys
from pathlib import Path
search = os.pathsep.join([str(Path.home() / '.local/bin'), os.environ.get('PATH', '')])
pattern = re.compile(sys.argv[1])
versions = {}
for harness, names in json.loads(sys.argv[2]):
    executable = next((p for n in names if (p := shutil.which(n, path=search))), None)
    version = None
    if executable:
        try:
            result = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=60)
            matched = pattern.search(result.stdout) if result.returncode == 0 else None
            version = matched.group(0).rstrip('-+._') if matched else None
        except (OSError, subprocess.TimeoutExpired):
            version = None
    versions[harness] = version
print(json.dumps(versions))
"""


def probe_harness_cli_versions(control: Any) -> dict[str, str | None]:
    """Return each harness id's live CLI version on the host, or None."""
    harnesses = [[r.harness_id, list(r.executables)] for r in HARNESS_CLI_RELEASES]
    result = control.run_command(
        [
            "/usr/bin/python3",
            "-c",
            _VERSION_PROGRAM,
            VERSION_TOKEN_PATTERN,
            json.dumps(harnesses),
        ],
        timeout=VERSION_PROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "harness_cli_version_probe_failed: the host could not report harness "
            f"CLI versions (exit {result.returncode}); repair SSH and "
            "/usr/bin/python3 on the host, then retry"
        )
    observed = json.loads(result.stdout)
    return {r.harness_id: observed.get(r.harness_id) for r in HARNESS_CLI_RELEASES}


def record_golden_harness_clis(control: Any, destination: str) -> HostActionResult:
    """Write the live harness CLI versions beside a just-captured golden."""
    sidecar = destination + GOLDEN_HARNESS_CLIS_SUFFIX
    try:
        versions = probe_harness_cli_versions(control)
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
    for harness_id in harness_ids:
        release = HARNESS_CLI_RELEASE_BY_ID[harness_id]
        result = control.run_command(
            ["/bin/sh", "-c", release.install_script, "sh", latest[harness_id]],
            timeout=INSTALL_TIMEOUT_SECONDS,
        )
        installs.append({"harness_id": harness_id, "exit_code": result.returncode})
        if result.returncode != 0:
            return HostActionResult(
                False,
                {
                    "installs": installs,
                    "recovery": (
                        f"Run the {harness_id} installer as the test user and read "
                        f"its error ({release.install_script}), repair it, then "
                        "rerun the QA plan."
                    ),
                },
                "harness_cli_install_failed",
            )
    observed = probe_harness_cli_versions(control)
    behind = [h for h in outdated_harness_clis(observed, latest) if h in harness_ids]
    evidence = {"installs": installs, "harness_cli_versions": observed}
    if behind:
        return HostActionResult(
            False,
            {
                **evidence,
                "latest": dict(latest),
                "recovery": (
                    "After install, " + ", ".join(behind) + " still resolves an "
                    "older CLI first on the test user's ~/.local/bin and PATH. "
                    "Remove the stale copy the probe found, then rerun the QA plan."
                ),
            },
            "harness_cli_install_unverified",
        )
    return HostActionResult(True, evidence)


__all__ = [
    "GOLDEN_HARNESS_CLIS_SUFFIX",
    "install_harness_clis",
    "probe_harness_cli_versions",
    "read_golden_harness_clis",
    "record_golden_harness_clis",
]
