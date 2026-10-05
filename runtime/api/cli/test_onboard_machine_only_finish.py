"""Account scope and next steps on machine-only wizard finish screens."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from runtime.api.cli.onboard_wizard_golden_capture import _stable_screenshot
from runtime.api.cli.onboard_wizard_golden_support import golden_color_env, make_app
from yoke_cli.config import onboard_project, yoke_token_verify
from yoke_cli.config.onboard_wizard_machine_finish import machine_finish_lines


def _connected_app(projects=None):
    app = make_app(api_url="https://app.upyoke.com/api/orgs/acme")
    app.result.yoke_token_verification = {
        "ok": True,
        "actor": {"label": "Ben Bauman"},
        "orgs": [{"name": "Acme"}],
        "projects": projects
        if projects is not None
        else [
            {"slug": "yoke", "public_item_prefix": "YOK"},
            {"slug": "platform", "public_item_prefix": "PLAT"},
            {"slug": "buzz", "public_item_prefix": "BUZ"},
        ],
    }
    return app


def _body(app):
    return "\n".join(
        str(widget.render()) for widget in app.query("#onboard-body Static")
    )


@pytest.mark.parametrize("screen", ["review", "success"])
@pytest.mark.parametrize("has_projects", [True, False])
def test_machine_only_finish_shows_account_scope(screen, has_projects):
    app = _connected_app(None if has_projects else [])

    async def scenario():
        with golden_color_env():
            async with app.run_test(size=(80, 40)) as pilot:
                await pilot.pause()
                if screen == "review":
                    app._goto_finish()
                else:
                    app._goto_apply_success()
                await app.workers.wait_for_complete()
                await pilot.pause()
                text = _body(app)
                assert "Connected as Ben Bauman · Acme" in text
                assert "Or open the dashboard: https://app.upyoke.com" in text
                assert "later, run: yoke setup" in text
                if has_projects:
                    assert chr(92) * 2 not in text
                    assert (
                        "Your projects: yoke (YOK) · platform (PLAT) · buzz (BUZ)"
                        in text
                    )
                    assert "You can file and browse work from any folder:" in text
                    assert 'yoke dash "Title" "what to do"' in text
                    assert "--project yoke --execution-instructions-considered" in text
                    assert (
                        "yoke workflow execution-instruction resolve --workflow dash"
                        in text
                    )
                    assert "yoke items list --project yoke" in text
                else:
                    assert "Your account has no projects yet." in text
                    assert "yoke dash" not in text
                    assert "yoke items list" not in text
                capture = os.environ.get("YOKE_MACHINE_FINISH_CAPTURE")
                if capture and has_projects and screen == "success":
                    svg = await _stable_screenshot(
                        pilot, app, "yoke setup · Machine ready"
                    )
                    Path(capture).write_text(svg, encoding="utf-8")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode",
    [
        onboard_project.PROJECT_MODE_CREATE_REPO,
        onboard_project.PROJECT_MODE_CLONE_REMOTE,
        onboard_project.PROJECT_MODE_IMPORT_REMOTE,
        onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE,
    ],
)
def test_project_setup_modes_keep_existing_finish(mode):
    app = _connected_app()
    app.result.project_mode = mode
    assert machine_finish_lines(app.result) == []
    assert app._review_status_lines() == [
        "Connection: Ben Bauman · 1 organizations · 3 projects"
    ]
    text = "\n".join(str(widget.render()) for widget in app._build_apply_success())
    assert "Your projects:" not in text
    assert "yoke setup" not in text


def test_older_server_projects_without_prefix_remain_usable():
    app = _connected_app([{"slug": "widget"}])
    app.result.api_url = "https://team.example.test/yoke/v1/"
    lines = machine_finish_lines(app.result)
    assert "Your projects: widget" in lines
    assert "Or open the dashboard: https://team.example.test/yoke" in lines
    assert "  yoke items list --project widget" in lines


def test_project_labels_are_literal_rich_text():
    app = _connected_app([{"slug": "[bold]widget", "public_item_prefix": "WID"}])
    widgets = app._build_apply_success()
    text = "\n".join(str(widget.render()) for widget in widgets)
    assert "[bold]widget (WID)" in text


def test_function_probe_preserves_existing_project_prefix(monkeypatch):
    requests = []

    def request(url, _token, *, body=None):
        requests.append(url)
        if url.endswith("/auth/identity"):
            raise yoke_token_verify._EndpointUnavailable
        if body:
            return {
                "success": True,
                "result": {
                    "rows": [
                        {"slug": "widget", "public_item_prefix": "WID"},
                    ]
                },
            }
        return []

    monkeypatch.setattr(yoke_token_verify, "_request_json", request)
    result = yoke_token_verify.verify("https://team.example.test", "fake-token")
    assert result["projects"][0]["public_item_prefix"] == "WID"
    assert len(requests) == 3
