"""Live GitHub authorization progress on the running checking screen.

The App device flow reports its one-time code, and then its installation URL,
while the check is still running. Both land on the checking screen's last plan
line and become the screen's copy and open targets, so the code and the link
can be carried to the browser without retyping them.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape

from yoke_cli.config.onboard_wizard_state import CopyTarget

BODY_ID = "onboard-body"
PLAN_LINE_CLASS = "onboard-plan-line"

CODE_LABEL = "the one-time code"
DEVICE_URL_LABEL = "the GitHub verification link"
INSTALL_URL_LABEL = "the App installation link"


def show_device_code(shell: Any, event: dict[str, Any]) -> None:
    """Report the device code and its verification URL as they are minted."""
    code = str(event.get("user_code") or "").strip()
    uri = str(event.get("verification_uri") or "").strip()
    if not (code and uri):
        return
    _report(
        shell,
        f"Enter code {code} at {uri}",
        (
            CopyTarget(CODE_LABEL, code),
            CopyTarget(DEVICE_URL_LABEL, uri, is_url=True),
        ),
    )


def show_install_url(shell: Any, event: dict[str, Any]) -> None:
    """Report the App installation URL once GitHub asks for the installation."""
    install_url = str(event.get("install_url") or "").strip()
    if not install_url:
        return
    _report(
        shell,
        f"Install or configure the App at {install_url}",
        (CopyTarget(INSTALL_URL_LABEL, install_url, is_url=True),),
    )


def _report(shell: Any, line: str, targets: tuple[CopyTarget, ...]) -> None:
    try:
        body = shell.query_one(f"#{BODY_ID}")
        plan_lines = [
            widget
            for widget in body.children
            if getattr(widget, "has_class", lambda _name: False)(PLAN_LINE_CLASS)
        ]
        if not plan_lines:
            return
        plan_lines[-1].update(escape(line))
        shell._set_copy_targets(targets)
    except Exception:
        return


__all__ = [
    "CODE_LABEL",
    "DEVICE_URL_LABEL",
    "INSTALL_URL_LABEL",
    "show_device_code",
    "show_install_url",
]
