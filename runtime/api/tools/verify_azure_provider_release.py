"""Read-only controller proof for Azure CLI discovery and live machine contracts."""

from __future__ import annotations

import argparse
import json
import subprocess

from yoke_contracts.machine_config.test_machine import validate_test_machine_settings


def _cli(*args):
    result = subprocess.run(
        ["yoke", *args], capture_output=True, text=True, check=False, timeout=90
    )
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} command failed: {result.stderr[-500:]}; "
            "use the deployed CLI release and retry this proof"
        )
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    project = parser.parse_args().project
    for verb in ("admin-link", "admin-status", "exec"):
        usage = _cli("azure", verb, "--help")
        if f"yoke azure {verb}" not in usage:
            raise RuntimeError(
                f"Azure {verb} is absent; install the delivered CLI release and retry"
            )
    response = json.loads(_cli("test-machine", "list", "--project", project, "--json"))
    if not response.get("success"):
        raise RuntimeError(
            "production Test Machine list refused; fix its named refusal and retry"
        )
    machines = response.get("result", {}).get("test_machines")
    if not isinstance(machines, list):
        raise RuntimeError(
            "production machine contract is missing; deploy the provider-capable server and retry"
        )
    for machine in machines:
        validate_test_machine_settings(machine["settings"])
    # No Azure VM or service-principal credentials are required for this proof.
    # Native Windows VM lifecycle acceptance belongs to its host-provisioning lane.
    validate_test_machine_settings(
        {
            "resource_name": "provider-proof",
            "host": "192.0.2.1",
            "user": "test",
            "os": "linux",
            "operating_notes": "",
            "cloud_provider": "azure",
            "cloud_instance_id": "/subscriptions/sub/resourceGroups/lab/providers/Microsoft.Compute/virtualMachines/vm",
        }
    )
    print(
        f"Azure admin command discovery passed; {len(machines)} production machine contracts validated; "
        "candidate accepts full Azure VM ids and provider selection"
    )


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
        OSError,
    ) as exc:
        raise SystemExit(
            f"azure_provider_release_proof_failed: {exc}; repair the named cause and rerun"
        ) from None
