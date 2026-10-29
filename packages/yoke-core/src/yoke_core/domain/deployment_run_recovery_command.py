"""Connection-qualified deployment recovery recipes."""

import shlex
import re

from yoke_contracts.machine_config import runtime as machine_config


def yoke_command() -> str:
    """Keep the selected connection on every recovery invocation."""
    try:
        env = machine_config.active_env()
    except RuntimeError:
        env = "ENV"
    return f"yoke --env {shlex.quote(env)}"


def deploy_command(run_id: str = "RUN-ID") -> str:
    return f"{yoke_command()} watch deploy -- {shlex.quote(run_id)}"


def qualify_commands(text: str) -> str:
    return re.sub(r"\byoke (?!-)", lambda _: yoke_command() + " ", text)
