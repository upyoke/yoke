"""Missing repositories remain reachable from a populated private picker."""

from __future__ import annotations

import asyncio

from yoke_cli.config import github_publish, hosted_machine_browser
from yoke_cli.config import onboard_wizard_flow_clone as clone_flow
from yoke_cli.config import onboard_wizard_project_screens as screens
from yoke_cli.config import project_git_probe, project_git_transport
from runtime.api.cli.onboard_wizard_test_helpers import (
    make_app, stub_path_doctor, stub_source_branch, type_text,
)
from runtime.api.cli.onboard_wizard_clone_visibility_support import (
    start_clone, wait_for_body_text, wait_for_selection,
)


VISIBLE = github_publish.RepoRef("acme/visible", "https://github.com/acme/visible.git", True)
MISSING = github_publish.RepoRef("acme/missing", "https://github.com/acme/missing.git", True)


def prepare(monkeypatch):
    stub_path_doctor(monkeypatch)
    stub_source_branch(monkeypatch, "main")
    monkeypatch.setattr(clone_flow, "fetch_private_repos", lambda *a, **kw: [VISIBLE])
    return make_app()[0]


def test_prompt_exposes_recovery_choices_to_interactive_and_agent_consumers():
    prompt = screens.repo_picker_prompt([VISIBLE])
    assert prompt.key == "project.private_repo"
    assert [(row.value, row.label) for row in prompt.choices] == [
        (VISIBLE.clone_url, VISIBLE.full_name),
        ("manage", "Not listed: grant access"),
        ("url", "Enter repository URL"),
    ]


def test_grant_access_from_populated_picker_then_refresh(monkeypatch):
    app = prepare(monkeypatch)
    opened = []
    monkeypatch.setattr(
        clone_flow.github_state, "repository_access_url",
        lambda _result: "https://github.com/settings/installations/1",
    )
    monkeypatch.setattr(
        clone_flow.setup_browser, "open_url",
        lambda url: opened.append(url) or hosted_machine_browser.BrowserOpenResult(
            opened=True, method="test-browser",
        ),
    )

    async def scenario():
        async with app.run_test() as pilot:
            await start_clone(app, pilot, connect_github=True)
            await pilot.press("down", "enter")
            await wait_for_selection(app, pilot)
            await type_text(pilot, "grant")
            await pilot.press("enter")
            await wait_for_body_text(app, pilot, "Choose repositories Yoke can access.")
            await pilot.pause()
            assert opened == ["https://github.com/settings/installations/1"]
            monkeypatch.setattr(
                clone_flow, "fetch_private_repos", lambda *a, **kw: [VISIBLE, MISSING],
            )
            await pilot.press("down", "enter")  # Check again after changing access.
            picker = await wait_for_selection(app, pilot)
            assert MISSING.clone_url in [row.value for row in picker.rows]

    asyncio.run(scenario())


def test_url_entry_uses_connected_probe_and_private_access_recovery(monkeypatch):
    app = prepare(monkeypatch)
    probes = []
    monkeypatch.setattr(
        clone_flow.github_state, "user_access_token", lambda _result: "ghu_connected",
    )

    def probe(url, **kwargs):
        probes.append((url, kwargs.get("token")))
        return project_git_probe.GitRemoteProbe(
            False, failure_kind=project_git_probe.FAILURE_ACCESS,
        )

    monkeypatch.setattr(project_git_transport, "remote_probe", probe)

    async def scenario():
        async with app.run_test() as pilot:
            await start_clone(app, pilot, connect_github=True)
            await pilot.press("down", "enter")
            await wait_for_selection(app, pilot)
            await type_text(pilot, "Enter")
            await pilot.press("enter")
            await pilot.pause()
            assert app._history[-1].prompt.key == "project.clone_url"
            await type_text(pilot, MISSING.clone_url)
            await pilot.press("enter")
            text = await wait_for_body_text(app, pilot, "Couldn't reach that repo.")
            assert "GitHub" in text
            assert "access" in text.lower()
            assert probes[0][0] == MISSING.clone_url
            assert probes == [(MISSING.clone_url, "ghu_connected"), (MISSING.clone_url, None)]
            assert "GitHub App has access to that repository" in text
            recovery = await wait_for_selection(app, pilot)
            assert [row.value for row in recovery.rows] == [
                "repositories", "retry", "back",
            ]
            await pilot.press("enter")
            refreshed = await wait_for_selection(app, pilot)
            assert VISIBLE.clone_url in [row.value for row in refreshed.rows]

    asyncio.run(scenario())
