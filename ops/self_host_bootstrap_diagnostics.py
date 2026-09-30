"""Redacted failure artifacts from the disposable native bootstrap bundle."""

from pathlib import Path
import subprocess
import urllib.request


def retain_failure_diagnostics(
    target: Path, evidence: Path, failure: Exception
) -> None:
    """Keep the failed operation and container logs without any bundle secrets."""
    secrets = [path.read_bytes().strip() for path in (target / "secrets").iterdir()]
    output = bytearray(
        getattr(failure, "compose_output", b"")
        + getattr(failure, "command_output", b"")
    )
    for args in (
        ("ps", "--all", "--format", "json"),
        ("logs", "--no-color", "--tail", "200", "core", "db"),
    ):
        result = subprocess.run(
            ("docker", "compose", *args),
            cwd=target,
            capture_output=True,
            timeout=30,
            check=False,
        )
        output.extend(result.stdout + result.stderr)
    containers = (
        subprocess.run(
            ("docker", "compose", "ps", "--all", "-q", "core"),
            cwd=target,
            capture_output=True,
            timeout=30,
            check=False,
        )
        .stdout.decode()
        .split()
    )
    for container in containers:
        result = subprocess.run(
            ("docker", "inspect", "--format", "{{json .State.Health}}", container),
            capture_output=True,
            timeout=30,
            check=False,
        )
        output.extend(result.stdout + result.stderr)
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:18765/v1/health", timeout=5
        ) as response:
            output.extend(response.read())
    except OSError:
        output.extend(b"probe_health_response_unavailable\n")
    redacted = bytes(output)
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            redacted = redacted.replace(secret, b"[redacted]")
    (evidence / "bootstrap-failure.log").write_bytes(redacted)
