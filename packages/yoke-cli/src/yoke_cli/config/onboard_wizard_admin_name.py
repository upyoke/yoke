"""Ask the installer's name: a new universe's first admin is that person."""

from __future__ import annotations

from typing import Callable

from yoke_contracts.first_admin_name import AdminNameError, validate_admin_name

TITLE = "What's your name?"
SUBTITLE = "Yoke creates this universe's first admin as you."


def prompt(
    shell,
    step: str,
    *,
    current: str | None,
    on_done: Callable[[str], None],
) -> None:
    """Open the shared input screen and hand back a validated name."""
    shell._goto_input(
        step,
        TITLE,
        SUBTITLE,
        placeholder="Your name",
        initial_value=current or "",
        allow_placeholder=False,
        validate=input_error,
        on_done=lambda value: on_done(validate_admin_name(value)),
    )


def ask_for_server(shell, setup, proceed: Callable[[], None]) -> None:
    """Ask before a new server bundle is written; an adopted one is born."""
    from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT

    if setup.bundle_created:
        proceed()
        return

    def named(name: str) -> None:
        setup.admin_name = name
        proceed()

    prompt(shell, STEP_CONNECT, current=setup.admin_name, on_done=named)


def input_error(value: str) -> str | None:
    try:
        validate_admin_name(value)
    except AdminNameError as exc:
        return str(exc)
    return None


__all__ = ["SUBTITLE", "TITLE", "ask_for_server", "input_error", "prompt"]
