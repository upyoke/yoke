"""Controller proof that cloud shell and verify preserve the host and power state."""

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
    parser.add_argument("--initial-state", choices=("running", "stopped"))
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

    def power_state():
        if provider == "aws":
            return json.loads(
                cloud(
                    "ec2",
                    "describe-instances",
                    "--instance-ids",
                    instance,
                    "--query",
                    "Reservations[0].Instances[0].State.Name",
                    "--output",
                    "json",
                )
            )
        return json.loads(
            cloud(
                "vm", "show", "--ids", instance, "--show-details",
                "--query", "powerState", "--output", "json",
            )
        )

    def check_running(operation):
        state = power_state()
        if state not in ("running", "VM running"):
            raise RuntimeError(
                f"tailnet_power_failed: {name} is {state} after {operation}; "
                "inspect the provider state and the command output"
            )
        print(f"{name} after {operation}: {state}", flush=True)

    state = power_state()
    initial_states = {
        "running": ("running", "VM running"),
        "stopped": ("stopped", "VM stopped", "VM deallocated"),
    }
    if args.initial_state and state not in initial_states[args.initial_state]:
        raise RuntimeError(
            f"tailnet_power_precondition: {name} is {state}; select an unleased "
            f"machine that is {args.initial_state} and rerun"
        )
    print(f"{name} before exec: {state}", flush=True)
    commands = ("--project", project, "--test-machine", name)
    output = run("test-machine", "exec", *commands, "--", "whoami", include_stderr=True)
    check_running("exec")
    output += run("test-machine", "verify", *commands, include_stderr=True)
    check_running("verify")
    if any(
        phrase in output.lower()
        for phrase in ("stopping instance", "deallocated azure vm")
    ) or (
        state in initial_states["running"] and "deallocated" in output.lower()
    ):
        raise RuntimeError(
            "tailnet_power_failed: lease release reported a provider stop; "
            "inspect the exec and verify output"
        )
    after = record()
    if after["settings"]["host"] != host or after.get("active_lease"):
        raise RuntimeError(
            "tailnet_power_failed: host changed or QA_HOST remains; inspect the execution receipt before recovery"
        )
    print(f"PASS {name}: host unchanged ({host}), running, no QA_HOST")


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise SystemExit(
            f"tailnet_power_proof_refused: {exc}; repair the named precondition and rerun this case"
        ) from None
