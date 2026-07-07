"""Support helpers for the local-core launcher."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote

from yoke_cli.config import writer as config_writer
from yoke_cli.local_core import docker_plan as dp
from yoke_cli.local_core import state
from yoke_cli.local_core.runner import CommandResult, CommandRunner

Issue = dp.Issue


def select_image(
    current: dict[str, Any],
    *,
    image: str | None,
    from_checkout: str | None,
    build: bool,
    action: str,
) -> tuple[str | None, list[Issue]]:
    issues: list[Issue] = []
    selected = image
    if from_checkout:
        issues.extend(checkout_issues(from_checkout))
        if not build:
            issues.append(dp.issue(
                "local_core_build_required",
                f"`yoke core {action} --from-checkout` requires `--build`",
                f"Use `yoke core {action} --from-checkout PATH --build`, "
                "or pass `--image IMAGE` for an already-built local/private "
                "image.",
            ))
        selected = selected or dp.local_image_for_checkout(from_checkout)
    if build and not from_checkout:
        issues.append(dp.issue(
            "local_core_checkout_required",
            f"`yoke core {action} --build` requires `--from-checkout PATH`",
            "Pass a Yoke source checkout path, or omit `--build` when using "
            "`--image IMAGE`.",
        ))
    selected = selected or current.get("image")
    if not selected:
        issues.append(dp.issue(
            "local_core_image_required",
            "no local-core image was selected",
            "Run `yoke core build --checkout PATH`, pass `--image IMAGE`, "
            f"or use `yoke core {action} --from-checkout PATH --build`.",
        ))
    return selected, issues


def checkout_issues(checkout_path: str) -> list[Issue]:
    checkout = Path(checkout_path).expanduser()
    if not checkout.exists():
        return [dp.issue(
            "checkout_not_found",
            "Yoke source checkout does not exist",
            f"Create or choose the checkout before retrying: {checkout}",
        )]
    if not checkout.is_dir():
        return [dp.issue(
            "checkout_not_directory",
            "Yoke source checkout path is not a directory",
            f"Choose the Yoke source checkout directory: {checkout}",
        )]
    if not (checkout / "Dockerfile").is_file():
        return [dp.issue(
            "checkout_missing_dockerfile",
            "Yoke source checkout does not contain a Dockerfile",
            "Pass the root of the Yoke source checkout.",
        )]
    return []


def write_env(machine_home: str | None, image: str) -> Any:
    existing = state.read_env_file(machine_home)
    password = existing.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(24)
    dsn = (
        f"postgresql://{dp.DB_USER}:{quote(password)}@"
        f"{dp.DB_CONTAINER}:5432/{dp.DB_NAME}"
    )
    return state.write_env_file({
        "POSTGRES_DB": dp.DB_NAME,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_USER": dp.DB_USER,
        "YOKE_API_PORT": str(dp.API_PORT_IN_CONTAINER),
        "YOKE_ENV": dp.ENV_NAME,
        "YOKE_LOCAL_CORE_IMAGE": image,
        "YOKE_PG_DSN": dsn,
    }, machine_home=machine_home)


def mint_token(
    runner: CommandRunner,
    machine_home: str | None,
    image: str,
) -> CommandResult:
    return runner.run(dp.token_plan(image, str(state.env_path(machine_home))),
                      timeout=60)


def configure_env(
    machine_home: str | None,
    api_url: str,
    token_stdout: str,
    config_path: str | None,
) -> Issue | None:
    try:
        token = json.loads(token_stdout).get("raw_token")
        if not isinstance(token, str) or not token:
            raise ValueError("token bootstrap returned no raw token")
        with state.machine_home_override(machine_home):
            config_writer.set_connection(
                dp.ENV_NAME,
                transport="https",
                api_url=api_url,
                token=token,
                prod=False,
                path=config_path,
            )
    except (ValueError, RuntimeError, config_writer.MachineConfigWriteError) as exc:
        return dp.issue(
            "machine_config_write_failed",
            "local-core API is running but machine env configuration failed",
            str(exc),
        )
    return None


__all__ = [
    "checkout_issues",
    "configure_env",
    "mint_token",
    "select_image",
    "write_env",
]
