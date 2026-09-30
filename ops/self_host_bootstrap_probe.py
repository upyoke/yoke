"""Manual Ubuntu/rootful Docker proof of the real self-host bootstrap path.

Builds the candidate image/wheels and starts as the non-root runner operator.
Artifacts contain identities and verdicts, never generated credentials.
Rootless Docker and Fedora/SELinux remain unproved.
"""

from __future__ import annotations

from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import tempfile
import time
import urllib.request


def file_identity(path: Path) -> dict:
    info = path.stat()
    return {
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": oct(stat.S_IMODE(info.st_mode)),
        "size": info.st_size,
    }


def command(args: list[str], *, cwd: Path, timeout: int = 180) -> str:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, timeout=timeout, check=False
    )
    if result.returncode:
        # Output may contain a credential; retain only command identity/status.
        raise RuntimeError(
            f"probe_command_failed: {args[:2]} exited {result.returncode}; inspect container logs and retry"
        )
    return result.stdout.decode().strip()


def assert_healthy(url: str, token: str, sha: str) -> dict:
    deadline = time.monotonic() + 120
    while True:
        try:
            with urllib.request.urlopen(url + "/v1/health", timeout=2) as response:
                health = json.load(response)
            break
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "probe_health_timeout: inspect core logs and retry"
                ) from None
            time.sleep(1)
    if health.get("build") != sha:
        raise RuntimeError(
            "probe_build_mismatch: rebuild the exact candidate and retry"
        )
    # The authenticated identity route is read-only; a 200 proves token use.
    request = urllib.request.Request(
        url + "/v1/auth/identity", headers={"Authorization": "Bearer " + token}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        authenticated = response.status
        response.read()
    return {
        "health": "passed",
        "served_build": health["build"],
        "authenticated_status": authenticated,
    }


def build_candidate(root: Path, evidence: Path, sha: str, wheel_dir: Path) -> str:
    image = f"localhost:5200/yoke-bootstrap:{sha[:12]}"
    with (evidence / "image-build.log").open("w") as capture:
        result = subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                f"YOKE_BUILD_SHA={sha}",
                "--build-arg",
                f"YOKE_ENGINE_VERSION={version('yoke-core')}",
                "-t",
                image,
                ".",
            ],
            cwd=root,
            stdout=capture,
            stderr=subprocess.STDOUT,
            timeout=1200,
            check=False,
        )
    if result.returncode:
        raise RuntimeError(
            "probe_image_build_failed: inspect image-build.log and fix the candidate build"
        )
    command(["docker", "push", image], cwd=root)
    for package in ("yoke-contracts", "yoke-cli"):
        command(
            [
                "uv",
                "build",
                "--wheel",
                "--package",
                package,
                "--out-dir",
                str(wheel_dir),
            ],
            cwd=root,
        )
    return image


def host_probe(evidence: Path, report: dict) -> None:
    from yoke_cli.self_host import bundle, first_boot_token, runtime

    root = Path(__file__).resolve().parent.parent
    if platform.system() != "Linux" or os.geteuid() == 0:
        raise RuntimeError(
            "probe_host_unsupported: run as the non-root ubuntu-latest operator"
        )
    docker = json.loads(command(["docker", "info", "--format", "{{json .}}"], cwd=root))
    if any(
        "rootless" in option or "userns" in option
        for option in docker["SecurityOptions"]
    ):
        raise RuntimeError(
            "probe_docker_unsupported: use rootful Docker without userns remapping"
        )
    sha = command(["git", "rev-parse", "HEAD"], cwd=root)
    report.update(
        {
            "scope": "Ubuntu rootful Docker; rootless Docker and Fedora/SELinux remain unproved",
            "candidate_sha": sha,
            "host": {
                "uid": os.getuid(),
                "gid": os.getgid(),
                "kernel": platform.release(),
                "os_release": Path("/etc/os-release").read_text(),
            },
            "docker": {
                key: docker[key]
                for key in (
                    "ServerVersion",
                    "SecurityOptions",
                    "OperatingSystem",
                    "Architecture",
                    "KernelVersion",
                )
            },
            "compose_version": command(["docker", "compose", "version"], cwd=root),
            "runner": {
                key: os.environ.get(key)
                for key in (
                    "ImageOS",
                    "ImageVersion",
                    "GITHUB_RUN_ID",
                    "GITHUB_RUN_ATTEMPT",
                )
            },
        }
    )
    with tempfile.TemporaryDirectory(prefix="yoke-bootstrap-probe-") as temporary:
        temporary = Path(temporary)
        wheel_dir = temporary / "wheels"
        image = build_candidate(root, evidence, sha, wheel_dir)
        target = temporary / "bundle"
        bundle.write_bundle(directory=str(target), port=18765, image=image)
        before = {
            path.name: file_identity(path) for path in (target / "secrets").iterdir()
        }
        report["host_inputs_before"] = before
        try:
            # This is the same host ingress used by init --start and the wizard.
            runtime.start_bundle(directory=target)
            token_path = first_boot_token.token_drop_path(target)
            token = first_boot_token.read_first_boot_token(target)
            if not token:
                raise RuntimeError(
                    "probe_token_missing: repair the descriptor handoff and retry"
                )
            report["first_boot"] = assert_healthy("http://127.0.0.1:18765", token, sha)
            identity = file_identity(token_path)
            assert identity["uid"] == os.getuid() and identity["mode"] == "0o600"
            report["host_token"] = {**identity, "operator_readable": True}
            for name, identity in before.items():
                assert file_identity(target / "secrets" / name) == identity
            report["host_inputs_unchanged"] = True
            core_id = command(["docker", "compose", "ps", "-q", "core"], cwd=target)
            inspected = json.loads(command(["docker", "inspect", core_id], cwd=target))[
                0
            ]
            report["container_security"] = {
                "cap_drop": inspected["HostConfig"]["CapDrop"],
                "cap_add": inspected["HostConfig"]["CapAdd"],
                "security_opt": inspected["HostConfig"]["SecurityOpt"],
                "secret_bind_mounts": [
                    m["Destination"] for m in inspected["Mounts"] if m["Type"] == "bind"
                ],
            }
            assert not report["container_security"]["secret_bind_mounts"]
            # PID 1 is the real server after the irreversible identity drop.
            status = command(
                ["docker", "compose", "exec", "-T", "core", "cat", "/proc/1/status"],
                cwd=target,
            )
            report["runtime_identity"] = {
                line.partition(":")[0]: line.partition(":")[2].strip()
                for line in status.splitlines()
                if line.startswith(
                    ("Uid:", "Gid:", "Groups:", "CapEff:", "NoNewPrivs:")
                )
            }
            assert set(report["runtime_identity"]["Uid"].split()) != {"0"}
            assert int(report["runtime_identity"]["CapEff"], 16) == 0
            runtime.start_bundle(directory=target)
            assert first_boot_token.read_first_boot_token(target) == token
            report["restart"] = assert_healthy("http://127.0.0.1:18765", token, sha)
            probe_upgrade(root, temporary, wheel_dir, target, image, sha)
            assert first_boot_token.read_first_boot_token(target) == token
            report["upgrade"] = {
                **assert_healthy("http://127.0.0.1:18765", token, sha),
                "distribution": "candidate wheel/installer fixture and local registry; production publication not exercised",
            }
            logs = command(
                ["docker", "compose", "logs", "--no-color", "core", "db"], cwd=target
            )
            assert token not in logs
            report["token_absent_from_logs"] = True
        except Exception as exc:
            retain_failure_diagnostics(target, evidence, exc)
            raise
        finally:
            command(
                ["docker", "compose", "down", "--volumes", "--remove-orphans"],
                cwd=target,
            )


def retain_failure_diagnostics(
    target: Path, evidence: Path, failure: Exception
) -> None:
    """Keep the failed operation and container logs without any bundle secrets."""
    secrets = [path.read_bytes().strip() for path in (target / "secrets").iterdir()]
    output = bytearray(getattr(failure, "compose_output", b""))
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


def probe_upgrade(
    root: Path, temporary: Path, wheels: Path, target: Path, image: str, sha: str
) -> None:
    environment = temporary / "client"
    command(["uv", "venv", "--seed", str(environment)], cwd=root)
    python = str(environment / "bin" / "python")
    command(
        ["uv", "pip", "install", "--python", python, *map(str, wheels.glob("*.whl"))],
        cwd=root,
    )
    cli_wheel = next(wheels.glob("yoke_cli-*.whl"))
    installer = temporary / "install.py"
    installer.write_text(
        "import argparse, subprocess, sys\n"
        "p=argparse.ArgumentParser(); p.add_argument('--version'); p.add_argument('--yes',action='store_true'); p.add_argument('--no-onboard',action='store_true'); p.add_argument('--base-url'); a=p.parse_args()\n"
        f"raise SystemExit(subprocess.call([sys.executable,'-m','pip','install','--force-reinstall','--no-deps',{str(cli_wheel)!r}]))\n"
    )
    command(
        [
            python,
            str(root / "ops/self_host_upgrade_probe.py"),
            str(target),
            image,
            sha,
            str(installer),
        ],
        cwd=temporary,
    )


def main() -> int:
    evidence = Path(os.environ["PROBE_EVIDENCE_DIR"])
    evidence.mkdir(parents=True, exist_ok=True)
    report = {}
    try:
        host_probe(evidence, report)
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        # Only our named refusals are safe evidence. Unexpected assertions/HTTP
        # failures are recorded by type so no credential can reach an artifact.
        report["error"] = (
            str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        )
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
