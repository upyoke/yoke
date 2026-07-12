"""Wizard coverage for local-universe project discovery and review copy."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.onboard_destinations import DESTINATION_LOCAL  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_local_destination_manifest_project_id_uses_local_universe(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "buzz"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 37}\n',
        encoding="utf-8",
    )
    local_calls = []

    def fail_hosted_lookup(**_kwargs):
        raise AssertionError("local mode must not use the hosted project lookup")

    def fake_local_lookup(**kwargs):
        local_calls.append(kwargs)
        return existing_project_lookup.ExistingProject(
            id=37,
            slug="buzz",
            name="Buzz",
            github_repo="",
            default_branch="main",
            public_item_prefix="BUZZ",
        )

    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        fail_hosted_lookup,
    )
    monkeypatch.setattr(
        existing_project_lookup,
        "find_local_by_project_id",
        fake_local_lookup,
    )
    config = tmp_path / "config.json"
    app, spy = make_app(WizardDefaults(
        config_path=str(config),
        destination=DESTINATION_LOCAL,
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            assert "Your Yoke lives on this machine." in _body_text(app)
            await pilot.press("enter")  # universe summary: Continue
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("enter")  # project: existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            title = next(
                str(w.render()) for w in app.query(".onboard-title").results(Static)
            )
            body = _body_text(app)
            assert title == "Existing Yoke project found."
            assert (
                "Local project metadata matched a local Yoke database project."
                in body
            )
            assert "local Yoke database: verified project id 37." in body
            await pilot.press("enter")  # continue -> board art
            await complete_board_art(pilot)
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    assert local_calls == [{"config_path": str(config), "project_id": 37}]
    applied = spy.applied
    assert applied is not None
    assert applied["destination"] == DESTINATION_LOCAL
    assert applied["existing_project_id"] == 37
    assert applied["project_slug"] == "buzz"


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("create", "Create this machine's local Yoke universe under ~/.yoke"),
        ("verify", "Verify this machine's existing local Yoke universe under ~/.yoke"),
        ("unavailable", "Check this machine's local Yoke universe connection under ~/.yoke"),
    ],
)
def test_local_universe_review_line(target: str, expected: str) -> None:
    assert steps._friendly_line("local-universe-init", target) == expected
