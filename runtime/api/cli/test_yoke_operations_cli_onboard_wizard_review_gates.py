"""Live-wizard coverage for the publish-PAT and Review pre-flight Apply gates.

Companion to the inline-validation suite: these two gates fire later in the flow
(at the publish-only PAT prompt and on the Review screen) and withhold the
forward action until the problem clears, rather than failing at Apply. Driven
through the real ``OnboardWizardApp`` pilot reading the live DOM.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import onboard_project  # noqa: E402

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


@pytest.fixture(autouse=True)
def _stub_owners(monkeypatch):
    from yoke_cli.config import github_publish
    from yoke_cli.config import onboard_wizard_flow

    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [github_publish.RepoOwner("octocat", "user")],
    )


async def _pick_mode(pilot, value: str) -> None:
    from yoke_cli.config import onboard_wizard_steps as steps

    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


async def _skip_machine_github(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down")   # machine github: Skip for now
    await pilot.press("enter")


def _body_text(app) -> str:
    return " ".join(
        str(w.render()) for w in app.query("#onboard-body Static").results(Static)
    )


# ── publish-only PAT publish-ability gate ────────────────────────────────


def _verification(*, can_publish: bool) -> dict:
    return {
        "identity": {"login": "machine-user"},
        "access": {"owners": ["machine-user"], "repos": ["machine-user/x"]},
        "capability": {
            "kind": "classic",
            "can_create": can_publish,
            "create_private": None,
            "can_push_new": can_publish,
            "can_publish": can_publish,
            "writable": [],
            "readonly": [],
            "see_private": 1,
            "see_public": 0,
            "write_probed_count": 0,
            "write_probe_total": 0,
        },
    }


def test_publish_pat_that_cannot_publish_blocks_inline(monkeypatch) -> None:
    """A publish-only PAT that can't create/push a new repo is blocked at entry.

    The pasted PAT is verified at the prompt; a can_publish=False token routes to
    the cannot-publish block screen instead of advancing to the owner picker and
    orphaning an empty repo at Apply.
    """
    from yoke_cli.config import onboard_wizard_flow_github as github_flow

    monkeypatch.setattr(
        github_flow, "verify_machine_github_token",
        lambda api_url, token: _verification(can_publish=False),
    )

    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CREATE_REPO)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug placeholder
            await pilot.press("enter")  # name placeholder
            await pilot.press("enter")  # publish: Yes (no machine token -> PAT prompt)
            await type_text(pilot, "ghp_cannot_publish")
            await pilot.press("enter")  # submit PAT -> verified -> blocked
            await pilot.pause()
            await pilot.pause()
            assert "can't publish a new repo" in _body_text(app).lower()
            assert app.result.project_publish_to_github is False

    asyncio.run(scenario())


def test_unverifiable_publish_pat_shows_retry(monkeypatch) -> None:
    """A publish-only PAT that fails verification shows a retry screen inline."""
    from yoke_cli.config import github_machine_verify
    from yoke_cli.config import onboard_wizard_flow_github as github_flow

    def _boom(api_url, token):
        raise github_machine_verify.GitHubMachineVerificationError("bad token")

    monkeypatch.setattr(github_flow, "verify_machine_github_token", _boom)

    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CREATE_REPO)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            await pilot.press("enter")  # publish: Yes -> PAT prompt
            await type_text(pilot, "ghp_bad")
            await pilot.press("enter")  # submit -> verify fails -> retry screen
            await pilot.pause()
            await pilot.pause()
            assert "could not be verified" in _body_text(app).lower()
            # The token was not accepted onto the result.
            assert app.result.machine_github_token is None

    asyncio.run(scenario())


# ── Review pre-flight blocks Apply ───────────────────────────────────────


def test_review_preflight_blocks_apply_until_clear(monkeypatch) -> None:
    """A pre-flight problem on the Review screen withholds Apply.

    The Review screen shows the problem and the only forward row is "Back to fix
    that"; pressing it (the position Apply would occupy) does NOT apply.
    """
    from yoke_cli.config.onboard_wizard_flow import WizardFlow
    from yoke_cli.config.onboard_preflight import PreflightResult

    # Force one pre-flight problem so the Review screen renders the blocked rows.
    monkeypatch.setattr(
        WizardFlow, "_review_preflight",
        lambda self: PreflightResult(
            problems=["That folder already has files — pick an empty or new path."],
            notes=[],
        ),
    )

    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            await pilot.press("down")   # publish: No
            await pilot.press("enter")
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix
            await complete_board_art(pilot)  # board art -> Review (blocked)
            await pilot.pause()
            body = _body_text(app)
            assert "to fix before applying" in body.lower()
            assert "already has files" in body.lower()
            # The first (default) row is "Back to fix that", not "Apply" — pressing
            # Enter steps back instead of applying.
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

    asyncio.run(scenario())

    # Nothing was applied — the pre-flight gate held.
    assert spy.applied is None
