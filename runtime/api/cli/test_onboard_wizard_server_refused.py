"""The server-refused setup screen names each recovery step once."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_golden_support import make_app, render  # noqa: E402
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402
from yoke_cli.transport import server_reach_failure  # noqa: E402


def test_server_refused_names_the_server_machine_check_once() -> None:
    app = make_app(api_url="")
    message = (
        f"{server_reach_failure.SERVER_REFUSED}: 127.0.0.1:9 refused the "
        f"connection. {server_reach_failure.CHECK_SERVER_MACHINE}"
    )

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_yoke_verify_error(message, "team-server")

    render(app, drive, title="yoke setup · Account")
    prompt = app._history[-1].prompt
    screen = "\n".join([prompt.message, *prompt.detail_lines])
    assert prompt.title == "Yoke could not use that server."
    assert screen.count(server_reach_failure.CHECK_SERVER_MACHINE) == 1
