"""Manual Ubuntu/rootful Docker confirmation of self-host private handoffs.

Run via self-host-bootstrap-probe.yml after that workflow lands on the default
branch. The JSON artifact records both handoffs, including expected refusals;
a successful diagnostic run is not a healthy-server claim. It builds the exact
candidate image and uses its unmodified generated Compose security policy.
No rootless/user-namespace or Fedora/SELinux coverage is claimed. Generated
credentials and bundle files are disposable and never enter the artifact.
"""

from __future__ import annotations

import argparse
import contextlib
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import platform
import pwd
import stat
import subprocess
import tempfile


def file_identity(path: Path) -> dict:
    info = path.stat()
    return {
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": oct(stat.S_IMODE(info.st_mode)),
        "size": info.st_size,
    }


def failure(exc: Exception) -> dict:
    cause = exc.__cause__
    return {
        "status": "refused",
        "reason": str(exc),
        "cause": str(cause) if cause else None,
        "errno": getattr(cause or exc, "errno", None),
    }


def process_identity() -> dict:
    status = Path("/proc/self/status").read_text().splitlines()
    return {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "groups": os.getgroups(),
        "uid_map": Path("/proc/self/uid_map").read_text().strip(),
        "gid_map": Path("/proc/self/gid_map").read_text().strip(),
        "capabilities": {
            key: value.strip()
            for line in status
            for key, _, value in [line.partition(":")]
            if key.startswith("Cap") or key == "NoNewPrivs"
        },
    }


def container_probe() -> dict:
    from yoke_core.tools import self_host_server_bootstrap as bootstrap
    from yoke_core.api.first_boot_admin_token_delivery import (
        deliver_first_boot_admin_token,
    )
    from yoke_contracts.self_host_bootstrap_output import FIRST_BOOT_TOKEN_FD_ENV

    account = pwd.getpwnam(bootstrap.SELF_HOST_RUNTIME_USER)
    paths = [Path("/run/secrets/yoke-db-dsn"), Path("/run/yoke-first-boot-admin-token")]
    report = {
        "bootstrap_identity": process_identity(),
        "runtime_account": {"uid": account.pw_uid, "gid": account.pw_gid},
        "files": {str(path): file_identity(path) for path in paths},
        "mountinfo": [
            line
            for line in Path("/proc/self/mountinfo").read_text().splitlines()
            if any(line.split()[4] == str(path) for path in paths)
        ],
    }
    try:
        env, targets = bootstrap.materialize_self_host_runtime_secrets(
            os.environ,
            runtime_uid=account.pw_uid,
            runtime_gid=account.pw_gid,
            require_read_only_sources=True,
        )
        report["input_materialization"] = {
            "status": "opened",
            "targets": [str(path) for path in targets],
        }
    except Exception as exc:
        report["input_materialization"] = failure(exc)

    # This is independent: the earlier input refusal must not hide this open.
    try:
        token_env = bootstrap.open_first_boot_token_drop(dict(os.environ))
        report["output_open"] = {"status": "opened"}
    except Exception as exc:
        report["output_open"] = failure(exc)
        token_env = None
    bootstrap.drop_to_self_host_runtime_identity(uid=account.pw_uid, gid=account.pw_gid)
    bootstrap.assert_no_effective_linux_capabilities()
    report["post_drop_identity"] = process_identity()
    if report["input_materialization"]["status"] == "opened":
        try:
            bootstrap.assert_runtime_secrets_readable(targets)
            report["post_drop_input_read"] = {"status": "readable"}
        except Exception as exc:
            report["post_drop_input_read"] = failure(exc)
    if token_env is None:
        report["output_write"] = {
            "status": "not_possible",
            "reason": "output open refused",
        }
    else:
        try:
            # Synthetic marker, not a credential minted by any universe.
            with contextlib.redirect_stdout(io.StringIO()):
                deliver_first_boot_admin_token("bootstrap-probe-marker", env=token_env)
            report["output_write"] = {"status": "written"}
        except Exception as exc:
            report["output_write"] = failure(exc)
        finally:
            os.close(int(token_env[FIRST_BOOT_TOKEN_FD_ENV]))
    return report


def command(
    args: list[str], *, cwd: Path, timeout: int = 120
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=cwd, text=True, capture_output=True, timeout=timeout
    )


def required(args: list[str], *, cwd: Path) -> str:
    result = command(args, cwd=cwd)
    if result.returncode:
        raise RuntimeError(
            f"probe_command_failed: {args[0:2]}: {result.stderr.strip()}; restore the tool and retry"
        )
    return result.stdout.strip()


def host_probe(evidence: Path, report: dict) -> None:
    from yoke_cli.self_host.bundle import write_bundle

    root = Path(__file__).resolve().parent.parent
    if platform.system() != "Linux" or os.geteuid() == 0:
        raise RuntimeError(
            "probe_host_unsupported: use a non-root ubuntu-latest runner user"
        )
    docker = json.loads(
        required(["docker", "info", "--format", "{{json .}}"], cwd=root)
    )
    security = docker["SecurityOptions"]
    if any("rootless" in option or "userns" in option for option in security):
        raise RuntimeError(
            "probe_docker_unsupported: use rootful Docker without userns remapping"
        )
    sha = required(["git", "rev-parse", "HEAD"], cwd=root)
    report.update(
        {
            "scope": "Ubuntu rootful Docker only; rootless and Fedora/SELinux are not covered",
            "candidate_sha": sha,
            "runner": {
                key: os.environ.get(key)
                for key in (
                    "ImageOS",
                    "ImageVersion",
                    "RUNNER_OS",
                    "RUNNER_ARCH",
                    "GITHUB_RUN_ID",
                    "GITHUB_RUN_ATTEMPT",
                )
            },
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
            "compose_version": required(["docker", "compose", "version"], cwd=root),
        }
    )
    image = f"yoke-bootstrap-probe:{sha[:12]}"
    with (evidence / "image-build.log").open("w") as capture:
        built = subprocess.run(
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
        )
    if built.returncode:
        raise RuntimeError(
            "probe_image_build_failed: inspect image-build.log, fix build prerequisites, then retry"
        )
    report["image_id"] = required(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], cwd=root
    )
    with tempfile.TemporaryDirectory(prefix="yoke-bootstrap-probe-") as temporary:
        bundle = Path(temporary) / "bundle"
        write_bundle(directory=str(bundle), image=image)
        secrets_dir = bundle / "secrets"
        report["host_files_before"] = {
            path.name: file_identity(path) for path in secrets_dir.iterdir()
        }
        compose = ["docker", "compose", "-p", f"bootstrap-probe-{os.getpid()}"]
        container_name = f"bootstrap-probe-{os.getpid()}"
        try:
            # Run the unchanged default bootstrap first; no DB is needed to
            # characterize the file opens that occur before server execution.
            try:
                actual = command(
                    compose + ["run", "--no-deps", "--name", container_name, "core"],
                    cwd=bundle,
                    timeout=45,
                )
                report["default_bootstrap"] = {
                    "exit_code": actual.returncode,
                    "stdout": actual.stdout,
                    "stderr": actual.stderr,
                }
            except subprocess.TimeoutExpired:
                report["default_bootstrap"] = {
                    "status": "timeout",
                    "reason": "bootstrap exceeded the 45-second observation window",
                }
                required(["docker", "stop", container_name], cwd=bundle)
            inspected = json.loads(
                required(["docker", "inspect", container_name], cwd=bundle)
            )[0]
            report["container_configuration"] = {
                "user": inspected["Config"]["User"],
                "entrypoint": inspected["Config"]["Entrypoint"],
                "cap_drop": inspected["HostConfig"]["CapDrop"],
                "cap_add": inspected["HostConfig"]["CapAdd"],
                "security_opt": inspected["HostConfig"]["SecurityOpt"],
                "mounts": inspected["Mounts"],
            }
            diagnostic = command(
                compose
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "python",
                    "--volume",
                    f"{Path(__file__).resolve()}:/probe.py:ro",
                    "core",
                    "/probe.py",
                    "--container",
                ],
                cwd=bundle,
            )
            if diagnostic.returncode:
                raise RuntimeError(
                    f"probe_container_failed: {diagnostic.stderr}; inspect runner logs and retry"
                )
            report["handoffs"] = json.loads(diagnostic.stdout)
            token = secrets_dir / "first-boot-admin-token"
            report["host_token_after"] = {
                **file_identity(token),
                "host_readable": os.access(token, os.R_OK),
                "marker_received": token.read_text().strip()
                == "bootstrap-probe-marker",
                "owner_only": token.stat().st_uid == os.getuid()
                and stat.S_IMODE(token.stat().st_mode) == 0o600,
            }
        finally:
            command(compose + ["down", "--volumes", "--remove-orphans"], cwd=bundle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    if args.container:
        print(json.dumps(container_probe(), indent=2))
        return 0
    evidence = Path(os.environ["PROBE_EVIDENCE_DIR"])
    evidence.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    try:
        host_probe(evidence, report)
        report["diagnostic_status"] = "complete"
    except Exception as exc:
        report["diagnostic_status"] = "failed"
        report["error"] = str(exc)
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["diagnostic_status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
