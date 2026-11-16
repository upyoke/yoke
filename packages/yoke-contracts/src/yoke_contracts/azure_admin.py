"""Azure service-principal login with a disposable, private Azure CLI cache."""

from __future__ import annotations

from contextlib import contextmanager
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from yoke_contracts.azure_cli_prerequisite import check_azure_cli
from yoke_contracts.machine_config.capability_secret_store import (
    read_machine_capability_secret,
)

CAPABILITY = "azure-admin"
SETTING_KEYS = ("tenant_id", "client_id", "subscription_id")
SECRET_KEY = "client_secret"


class AzureAdminError(RuntimeError):
    """An Azure command failed without exposing its credential-bearing arguments."""


def _run(argv: list[str], *, env: dict[str, str], timeout: int):
    return subprocess.run(
        argv, env=env, capture_output=True, text=True, timeout=timeout, check=False
    )


def run_checked(
    run: Callable[..., Any],
    argv: list[str],
    env: dict[str, str],
    *,
    action: str,
    timeout: int = 60,
    secret: str = "",
) -> Any:
    try:
        result = run(argv, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        # TimeoutExpired carries the login argv, including the client secret.
        raise AzureAdminError(
            f"Azure {action} could not finish ({type(exc).__name__}); "
            "check network access and `az --version`, then retry"
        ) from None
    if result.returncode:
        detail = (result.stderr or result.stdout or "no diagnostic").strip()
        if secret:
            detail = detail.replace(secret, "[redacted]")
        raise AzureAdminError(
            f"Azure {action} failed: {detail[:500]}; "
            "check the service principal permissions and retry"
        )
    return result


@contextmanager
def azure_session(
    project: str, settings: Mapping[str, Any], *, run: Callable[..., Any] = _run
) -> Iterator[tuple[str, dict[str, str]]]:
    missing = [key for key in SETTING_KEYS if not str(settings.get(key) or "").strip()]
    secret = read_machine_capability_secret(project, CAPABILITY, SECRET_KEY)
    if missing or not secret:
        raise AzureAdminError(
            f"azure-admin is incomplete (missing {', '.join(missing + ([] if secret else [SECRET_KEY]))}); "
            f"run `yoke azure admin-link --project {project}` and follow its setup commands"
        )
    cli = check_azure_cli()
    with tempfile.TemporaryDirectory(prefix="yoke-azure-") as cache:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("AZURE_", "ARM_"))
        }
        env.update(
            AZURE_CONFIG_DIR=cache,
            AZURE_CORE_COLLECT_TELEMETRY="false",
            AZURE_EXTENSION_USE_DYNAMIC_INSTALL="no",
        )
        run_checked(
            run,
            [
                cli.executable,
                "login",
                "--service-principal",
                "--username",
                str(settings["client_id"]),
                f"--password={secret}",
                "--tenant",
                str(settings["tenant_id"]),
                "--output",
                "none",
            ],
            env,
            action="service-principal login",
            secret=secret,
        )
        run_checked(
            run,
            [
                cli.executable,
                "account",
                "set",
                "--subscription",
                str(settings["subscription_id"]),
            ],
            env,
            action="subscription selection",
            secret=secret,
        )
        yield cli.executable, env
