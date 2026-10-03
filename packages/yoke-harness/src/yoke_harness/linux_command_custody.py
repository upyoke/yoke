"""Require remote termination evidence before reporting an SSH GUI command settled."""

import json
from pathlib import Path
import shlex
import subprocess
import uuid

from yoke_harness import linux_command_supervisor as remote


def _program(expression, *arguments):
    source = Path(remote.__file__).read_text()
    return shlex.join(
        [
            "/usr/bin/python3",
            "-c",
            source + "\n" + expression,
            *[json.dumps(argument) for argument in arguments],
        ]
    )


def run_command(control, argv, environment, *, timeout):
    directory = "/tmp/yoke-command-" + uuid.uuid4().hex
    command_id = Path(directory).name
    command = _program(
        "run_supervised(*[json.loads(a) for a in sys.argv[1:]])",
        directory,
        argv,
        environment,
        timeout,
    )
    result = control._run(command, timeout=timeout + remote.SETTLEMENT_ALLOWANCE)
    receipt = None
    lines = []
    for line in result.stderr.replace(remote.HEARTBEAT, "").splitlines(keepends=True):
        if line.startswith(remote.RECEIPT_MARKER):
            try:
                receipt = json.loads(line.removeprefix(remote.RECEIPT_MARKER))
            except ValueError:
                pass
        else:
            lines.append(line)
    result.stderr = "".join(lines)
    if receipt is None:
        recovered = control._run(
            _program(
                "print(json.dumps(read_result(*[json.loads(a) for a in sys.argv[1:]])))",
                directory,
                remote.SETTLEMENT_ALLOWANCE,
            ),
            timeout=remote.SETTLEMENT_ALLOWANCE + 2,
        )
        try:
            recovered_result = (
                json.loads(recovered.stdout) if recovered.returncode == 0 else None
            )
            if isinstance(recovered_result, dict):
                receipt = recovered_result.get("receipt")
                if (
                    isinstance(receipt, dict)
                    and receipt.get("command_id") == command_id
                ):
                    result.stdout = recovered_result.get("stdout", result.stdout)
                    result.stderr = recovered_result.get("stderr", result.stderr)
                    for secret in getattr(control, "secret_values", ()):
                        result.stdout = result.stdout.replace(secret, "[REDACTED]")
                        result.stderr = result.stderr.replace(secret, "[REDACTED]")
        except ValueError:
            receipt = None
    if (
        not isinstance(receipt, dict)
        or receipt.get("command_id") != command_id
        or receipt.get("termination_verified") is not True
    ):
        return subprocess.CompletedProcess(
            argv,
            69,
            result.stdout,
            result.stderr + f"\nlinux_command_custody_unsettled: {directory}; "
            "remote termination could not be verified; retain this recovery handle",
        )
    result.returncode = int(receipt["returncode"])
    result.command_custody = receipt
    # A cleanup failure retains a private receipt; it cannot invalidate settlement.
    control._run(
        _program("remove_settled(json.loads(sys.argv[1]))", directory), timeout=5
    )
    return result
