# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import asyncio

import json

from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_wizard_flow_github as github_flow  # noqa: E402

from yoke_cli.config import onboard_machine_github  # noqa: E402

from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402

from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402

from yoke_cli.config.onboard_wizard_widgets import SelectionList  # noqa: E402

from textual.widgets import Static  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)


def _stored_revoked_config(tmp_path: Path) -> tuple[Path, Path]:
    credential = tmp_path / "github-app-user-legacy.json"
    credential.write_bytes(b"legacy-refresh-document\n")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "github": {
                    "client_id": "Iv1.product",
                    "app_slug": "yoke-product",
                    "app_id": 123,
                    "api_url": "https://api.github.com",
                    "web_url": "https://github.com",
                    "authorization": {
                        "kind": "github_app_user_authorization",
                        "refresh_credential_ref": str(credential),
                        "status": "revoked",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return config, credential


def _app(config: Path):
    return make_app(
        WizardDefaults(
            config_path=str(config),
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
        )
    )[0]


def _row_values(app) -> list[str]:
    selection = app.query_one("#onboard-body SelectionList", SelectionList)
    return [row.value for row in selection.rows]


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )
