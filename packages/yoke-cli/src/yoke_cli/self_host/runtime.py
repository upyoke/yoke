"""Host-owned secret ingress for every self-host start and restart."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import threading
import uuid

from yoke_cli.self_host import bundle, first_boot_token, protection
from yoke_contracts.self_host_bootstrap_output import is_api_token
from yoke_contracts.self_host_handoff import (
    CORE_SECRETS,
    DB_PASSWORD_INGRESS,
    HANDOFF_ACK,
    HANDOFF_CLIENT_MODULE,
    HANDOFF_TIMEOUT_SECONDS,
)


class SelfHostRuntimeError(RuntimeError):
    """The bootstrap refused without exposing credentials."""


def _refuse(reason: str, directory: Path) -> SelfHostRuntimeError:
    return SelfHostRuntimeError(
        f"{reason}: self-host bootstrap did not complete; inspect `docker compose "
        f"logs core db` in {directory}, repair the named input, then retry "
        f"`yoke self-host init --dir {directory} --protect-existing --start`"
    )


def read_secret(path: Path, *, max_bytes: int = 1 << 16) -> bytes:
    """Open the current operator's single-link 0600 input without following links."""
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or not 0 < info.st_size <= max_bytes
        ):
            raise ValueError("unsafe input")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read(max_bytes + 1)
        if not 0 < len(payload) <= max_bytes:
            raise ValueError("invalid input size")
        return payload
    except (OSError, ValueError):
        raise SelfHostRuntimeError(
            f"self_host_handoff_secret_invalid: {path.name} must be a readable "
            "current-owner single-link regular file at mode 0600, with bounded "
            "nonempty contents; repair that file and retry self-host init --start"
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def compose(
    directory: Path,
    executable: str,
    args: tuple[str, ...],
    *,
    input: bytes | None = None,
) -> bytes:
    """Keep all Docker output private; surface only a named recovery on failure."""
    try:
        result = subprocess.run(
            (executable, "compose", *args),
            cwd=directory,
            input=input,
            capture_output=True,
            timeout=HANDOFF_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode:
            raise _refuse("self_host_compose_failed", directory)
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        raise _refuse("self_host_compose_unavailable", directory) from None


def bootstrap_inputs(directory: Path, executable: str) -> tuple[bytes, bytes]:
    """Validate/open every secret on the host before starting any container."""
    try:
        directory = bundle.validate_existing_bundle(directory=str(directory))
        config = json.loads(
            compose(directory, executable, ("config", "--format", "json"))
        )
        environment = config["services"]["core"]["environment"]
        if environment.get("YOKE_SELF_HOST_HANDOFF") != "required":
            raise _refuse("self_host_compose_outdated", directory)
        payloads = {
            spec.env_name: base64.b64encode(
                read_secret(
                    directory / bundle.SECRETS_DIR_NAME / spec.host_name,
                    max_bytes=spec.max_bytes,
                )
            ).decode("ascii")
            for spec in CORE_SECRETS
            if spec.required or environment.get(spec.env_name)
        }
        password = read_secret(
            directory / bundle.SECRETS_DIR_NAME / bundle.DB_PASSWORD_FILE_NAME
        )
        return password, (json.dumps(payloads) + "\n").encode()
    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        bundle.SelfHostBundleError,
    ):
        raise _refuse("self_host_compose_invalid", directory) from None


def start_database(directory: Path, executable: str, password: bytes) -> None:
    compose(directory, executable, ("up", "--no-deps", "-d", "--force-recreate", "db"))
    compose(
        directory,
        executable,
        ("exec", "-T", "--user", "0", "db", "sh", "-c", DB_PASSWORD_INGRESS),
        input=password,
    )
    compose(
        directory, executable, ("up", "-d", "--wait", "--wait-timeout", "120", "db")
    )


def start_bundle(*, directory: str | Path, executable: str = "docker") -> dict:
    """Start/recreate the pair and durably receive a first-boot token if minted."""
    target = Path(directory).resolve()
    password, header = bootstrap_inputs(target, executable)
    start_database(target, executable, password)
    compose(target, executable, ("up", "--no-deps", "-d", "--force-recreate", "core"))
    _receive_token(target, executable, header)
    compose(target, executable, ("up", "-d", "--wait", "--wait-timeout", "120", "core"))
    return {"ok": True, "directory": str(target), "healthy": True}


def _receive_token(directory: Path, executable: str, header: bytes) -> None:
    command = (
        executable,
        "compose",
        "exec",
        "-T",
        "--user",
        "0",
        "core",
        "python",
        "-m",
        HANDOFF_CLIENT_MODULE,
    )
    process = None
    try:
        process = subprocess.Popen(
            command,
            cwd=directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.stdin.write(header)
        process.stdin.flush()
        if not select.select([process.stdout], [], [], HANDOFF_TIMEOUT_SECONDS)[0]:
            raise _refuse("self_host_handoff_timeout", directory)
        result = json.loads(process.stdout.readline(1024))
        token = result.get("token")
        if token is not None:
            if not isinstance(token, str) or not is_api_token(token):
                raise _refuse("self_host_handoff_token_invalid", directory)
            target = first_boot_token.token_drop_path(directory)
            if target.exists():
                first_boot_token.require_token_drop(directory)
            protection.atomic_replace_bytes(target, (token + "\n").encode(), mode=0o600)
            process.stdin.write(HANDOFF_ACK)
            process.stdin.flush()
        elif result.get("healthy") is not True:
            raise _refuse("self_host_handoff_receipt_invalid", directory)
        process.communicate(timeout=HANDOFF_TIMEOUT_SECONDS)
        if process.returncode:
            raise _refuse("self_host_handoff_failed", directory)
    except (
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
        protection.SelfHostProtectionError,
        first_boot_token.FirstBootTokenError,
        AttributeError,
    ):
        raise _refuse("self_host_handoff_failed", directory) from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()


def import_universe(directory: Path, *, archive=None, recover: bool = False) -> bytes:
    """Prepare the same private inputs before streaming an import or recovery."""
    from yoke_contracts.self_host_bootstrap import (
        IMPORT_UNIVERSE_ARG,
        RECOVER_IMPORT_CREDENTIAL_ARG,
    )

    password, header = bootstrap_inputs(directory, "docker")
    start_database(directory, "docker", password)
    name = "yoke-import-" + uuid.uuid4().hex
    selector = RECOVER_IMPORT_CREDENTIAL_ARG if recover else IMPORT_UNIVERSE_ARG
    compose(
        directory,
        "docker",
        ("run", "-d", "--no-deps", "--name", name, "core", selector),
    )
    process = None
    errors = []
    try:
        process = subprocess.Popen(
            (
                "docker",
                "exec",
                "-i",
                "--user",
                "0",
                name,
                "python",
                "-m",
                HANDOFF_CLIENT_MODULE,
                "--stream",
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ingress = process.stdin
        process.stdin = None

        def send():
            try:
                with ingress:
                    ingress.write(header)
                    if archive is not None:
                        while chunk := archive.read(65536):
                            ingress.write(chunk)
            except OSError as exc:
                errors.append(exc)

        sender = threading.Thread(target=send, daemon=True)
        sender.start()
        output, _ = process.communicate(timeout=HANDOFF_TIMEOUT_SECONDS)
        sender.join(timeout=HANDOFF_TIMEOUT_SECONDS)
        if process.returncode or errors or sender.is_alive():
            raise _refuse("self_host_import_handoff_failed", directory)
        return output
    except (OSError, subprocess.TimeoutExpired):
        raise _refuse("self_host_import_handoff_failed", directory) from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        subprocess.run(
            ("docker", "rm", "-f", name), capture_output=True, timeout=30, check=False
        )
