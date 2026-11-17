"""Controller proof: one stopped cloud lab verifies without changing its host."""

import argparse
import json
import subprocess


def run(*args, document=False, include_stderr=False):
    result = subprocess.run(
        ["yoke", *args], text=True, capture_output=True, timeout=1800
    )
    if result.returncode:
        raise RuntimeError(
            f"{' '.join(args)} refused: {result.stderr[-2000:]} {result.stdout[-2000:]}"
        )
    if document:
        value = json.loads(result.stdout)
        if not value.get("success"):
            raise RuntimeError(str(value.get("error")))
        return value["result"]
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", flush=True)
    return result.stdout + (result.stderr if include_stderr else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--test-machine", required=True)
    args = parser.parse_args()
    project, name = args.project, args.test_machine

    def record():
        return run(
            "test-machine",
            "get",
            "--project",
            project,
            "--test-machine",
            name,
            "--json",
            document=True,
        )

    before = record()
    settings = before["settings"]
    host = settings["host"]
    if not host.endswith(".ts.net") or before.get("active_lease"):
        raise RuntimeError(
            "tailnet_power_precondition: register MagicDNS and wait for the active host lease before rerunning"
        )
    provider = settings.get("cloud_provider", "aws")
    instance = settings["cloud_instance_id"]

    def cloud(*argv):
        return run(provider, "exec", "--project", project, "--", *argv)

    key = "QA_HOST:" + name
    run(
        "claims",
        "coordination-claim",
        "acquire",
        "--project",
        project,
        "--key",
        key,
        "--reason",
        "stop cloud lab before live power proof",
        "--json",
        document=True,
    )
    try:
        if provider == "aws":
            cloud("ec2", "stop-instances", "--instance-ids", instance)
            cloud("ec2", "wait", "instance-stopped", "--instance-ids", instance)
        else:
            cloud("vm", "deallocate", "--ids", instance)
    finally:
        run(
            "claims",
            "coordination-claim",
            "release",
            "--project",
            project,
            "--key",
            key,
            "--reason",
            "stopped state prepared for power proof",
            "--json",
            document=True,
        )
    print(f"stopped {name}; registered host {host}", flush=True)
    output = run(
        "test-machine",
        "verify",
        "--project",
        project,
        "--test-machine",
        name,
        include_stderr=True,
    )
    after = record()
    if after["settings"]["host"] != host or after.get("active_lease"):
        raise RuntimeError(
            "tailnet_power_failed: host changed or QA_HOST remains; inspect the execution receipt before recovery"
        )
    if provider == "aws":
        cloud("ec2", "wait", "instance-stopped", "--instance-ids", instance)
    else:
        state = json.loads(
            cloud(
                "vm",
                "show",
                "--ids",
                instance,
                "--show-details",
                "--query",
                "powerState",
                "--output",
                "json",
            )
        )
        group = instance.split("/resourceGroups/", 1)[1].split("/", 1)[0]
        ips = json.loads(
            cloud(
                "network",
                "public-ip",
                "list",
                "--resource-group",
                group,
                "--output",
                "json",
            )
        )
        if state != "VM deallocated" or ips:
            raise RuntimeError(
                "tailnet_power_failed: Azure allocation/IP remains; inspect its stop failure and retry cleanup"
            )
        if (
            "attached Azure public IP" not in output
            or "deleted Azure public IP" not in output
        ):
            raise RuntimeError(
                "tailnet_power_failed: missing Azure create/delete evidence; inspect the verify output"
            )
    print(
        f"PASS {name}: host unchanged ({host}), stopped, no QA_HOST"
        + (", no Azure public IP" if provider == "azure" else "")
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(
            f"tailnet_power_proof_refused: {exc}; repair the named precondition and rerun this case"
        ) from None
