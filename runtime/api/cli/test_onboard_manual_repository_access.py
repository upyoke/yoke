"""Exact manual-publication access recovery and navigation contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from yoke_cli.config import onboard_wizard_flow_publish_manual as manual
from yoke_cli.config import onboard_wizard_manual_access as recovery
from yoke_cli.config import onboard_wizard_project_github as project_access
from yoke_cli.config import onboard_destinations


TARGET = "acme/new-project"
UNRELATED = "other/existing"
SETTINGS = "https://github.com/organizations/acme/settings/installations/7"


def _repo(name=TARGET):
    return {
        "full_name": name,
        "repository_id": 81,
        "installation_id": 7,
        "private": True,
    }


def _report(repositories, *, listing_ok=True, contents="write"):
    return {
        "identity": {"checked": True, "ok": True, "login": "octocat"},
        "access": {
            "repo_listing_ok": listing_ok,
            "installations": [
                {"installation_id": 7, "permissions": {"contents": contents}}
            ],
            "repositories": repositories,
        },
    }


class Flow(manual.ManualPublishFlow, project_access.ProjectGithubAccessFlow):
    def __init__(self):
        self.result = SimpleNamespace(
            config_path=None,
            machine_github_api_url="",
            machine_github_verification=None,
            destination=onboard_destinations.DESTINATION_LOCAL,
            api_url="",
            project_github_repo=None,
        )
        self.attached = None
        self.backs = 0

    def _goto(self, view):
        self.view = view
        self.body = view.builder()

    def _goto_input(self, *args, **kwargs):
        self.input = kwargs

    def _run_checking(self, **kwargs):
        self.checking = kwargs

    def _after_repo(self, name):
        self.attached = name

    async def action_back(self):
        self.backs += 1


@pytest.fixture
def flow(monkeypatch):
    # Preserve all row/callback behavior without mounting Textual for each case.
    monkeypatch.setattr(
        manual.steps,
        "verification_body",
        lambda title, subtitle, details, rows, **_: (details, rows),
    )
    monkeypatch.setattr(
        manual.steps, "selection_body", lambda title, subtitle, rows: ([], rows)
    )
    return Flow()


def _choices(flow):
    return [row.value for row in flow.body[1]]


def _identify(flow, name=TARGET):
    flow._on_manual_publish_repository(recovery.MISSING_REPOSITORY)
    assert flow.input["validate"](name) is None
    assert flow.input["allow_placeholder"] is False
    flow.input["on_done"](name)


@pytest.mark.parametrize("opened", [True, False, RuntimeError("browser unavailable")])
def test_missing_repo_grants_owner_settings_then_rechecks_exact_identity(
    flow, monkeypatch, opened
):
    config = {
        "installations": [
            {"installation_id": 7, "account_login": "acme", "html_url": SETTINGS}
        ],
    }
    monkeypatch.setattr(
        project_access.machine_config, "github_config", lambda _: config
    )
    urls = []

    def browser(url):
        urls.append(url)
        if isinstance(opened, BaseException):
            raise opened
        return opened

    monkeypatch.setattr(project_access.webbrowser, "open", browser)
    flow._after_manual_publish_refresh(_report([_repo(UNRELATED)]))
    assert recovery.GRANT_ACCESS not in _choices(flow)
    _identify(flow)
    assert flow.attached is None
    assert _choices(flow) == [
        manual.CHECK_REPOSITORIES,
        recovery.GRANT_ACCESS,
        manual.DISABLED,
        manual.BACK,
    ]
    flow._on_manual_publish_recovery(recovery.GRANT_ACCESS)
    assert urls == [SETTINGS]
    assert SETTINGS in " ".join(flow.body[0])
    if opened is not True:
        assert "browser did not open" in " ".join(flow.body[0])
    flow._on_manual_publish_recovery(manual.CHECK_REPOSITORIES)
    assert flow.checking["replace_current"] is True
    assert flow.checking["blocks_quit"] is True
    assert not flow._manual_publish_access_missing
    calls = []
    monkeypatch.setattr(
        manual.github_machine,
        "status",
        lambda **kwargs: calls.append(kwargs) or _report([_repo(UNRELATED), _repo()]),
    )
    flow.checking["on_success"](flow.checking["work"]())
    assert calls[0]["check"] is True
    assert calls[0]["local_connection_selected"] is True
    assert _choices(flow)[0] == TARGET
    assert UNRELATED not in _choices(flow)
    assert recovery.GRANT_ACCESS not in _choices(flow)
    flow._on_manual_publish_repository(TARGET.upper())
    assert flow.attached == TARGET
    assert flow.result.project_publish_repository_id == 81
    assert flow.result.project_publish_installation_id == 7


@pytest.mark.parametrize(
    "failure", [_report([], listing_ok=False), RuntimeError("network_timeout: retry")]
)
def test_refresh_failure_never_offers_grant_and_invalidates_prior_missing_proof(
    flow, monkeypatch, failure
):
    flow._after_manual_publish_refresh(_report([]))
    _identify(flow)
    if isinstance(failure, BaseException):
        flow._manual_publish_refresh_error(failure)
    else:
        flow._after_manual_publish_refresh(failure)
    assert _choices(flow) == [manual.CHECK_REPOSITORIES, manual.DISABLED, manual.BACK]
    assert "Access is unknown" in " ".join(flow.body[0])
    monkeypatch.setattr(
        flow, "_open_project_github_access", lambda **_: pytest.fail("unproven grant")
    )
    flow._on_manual_publish_recovery(recovery.GRANT_ACCESS)
    assert flow.attached is None
    # Returning to an older identity form cannot turn failed refresh into proof.
    flow._after_manual_repository_identity(TARGET)
    assert recovery.GRANT_ACCESS not in _choices(flow)


def test_visible_but_not_writable_repository_teaches_permission_retry(flow):
    flow._after_manual_publish_refresh(_report([_repo()], contents="read"))
    _identify(flow)
    assert recovery.GRANT_ACCESS not in _choices(flow)
    assert flow.attached is None


def test_missing_identity_does_not_adopt_unrelated_repo_or_accept_stale_choice(flow):
    flow._after_manual_publish_refresh(_report([_repo(UNRELATED)]))
    _identify(flow)
    flow._on_manual_publish_repository(UNRELATED)
    assert flow.attached is None
    assert not flow._manual_publish_access_missing


@pytest.mark.parametrize(
    "name", ["owner", "https://github.com/acme/repo", "acme/repo/extra", ""]
)
def test_repository_identity_requires_owner_and_name(flow, name):
    flow._after_manual_publish_refresh(_report([]))
    flow._on_manual_publish_repository(recovery.MISSING_REPOSITORY)
    assert flow.input["validate"](name)
    flow.input["on_done"](name)
    assert flow.attached is None
    assert recovery.GRANT_ACCESS not in _choices(flow)


def test_already_accessible_explicit_identity_skips_settings(flow):
    flow._after_manual_publish_refresh(_report([_repo(), _repo(UNRELATED)]))
    _identify(flow, TARGET.upper())
    assert _choices(flow)[0] == TARGET
    assert recovery.GRANT_ACCESS not in _choices(flow)


def test_skip_and_back_work_during_missing_access_recovery(flow):
    flow._after_manual_publish_refresh(_report([]))
    _identify(flow)

    async def back():
        flow._on_manual_publish_recovery(manual.BACK)
        await asyncio.sleep(0)

    asyncio.run(back())
    assert flow.backs == 1
    assert flow.attached is None
    flow._on_manual_publish_recovery(manual.DISABLED)
    assert flow.attached == ""
    assert flow.result.project_publish_to_github is False
    assert flow.result.project_github_repository_id is None
    assert flow.result.project_github_installation_id is None
