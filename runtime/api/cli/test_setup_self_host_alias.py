"""A private machine approval preserves its connection name through Apply."""

from dataclasses import replace
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_approvals_test_support import (
    TOKEN,
    VERIFIED,
    Server,
    _only_browser,
)
from runtime.api.cli.setup_agent_test_support import (
    AgentDriver,
    git_checkout,
    isolate_agent_setup,
)
from runtime.api.cli.test_setup_agent_replay import walk_to_review
from yoke_cli.config import (
    hosted_machine_authorization as auth,
    setup_release_start,
    team_server_authorization,
    yoke_token_verify,
)
from yoke_contracts.machine_config import reader as machine_config

ORIGIN = "https://private-yoke.example"
ORG = "appliance-org"


@pytest.mark.parametrize("alias", ["private-lab", None])
def test_own_machine_approval_and_preset_free_apply(monkeypatch, tmp_path, capsys, alias):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    drive = AgentDriver(capsys)
    server = Server()
    checkout = git_checkout(tmp_path / "demo")
    verified = []

    def start(origin, *, self_host):
        assert origin == ORIGIN and self_host
        return replace(server.start(), platform_url=origin, self_host=True)

    def verify(url, token):
        assert (url, token) == (ORIGIN, TOKEN)
        verified.append(url)
        return VERIFIED

    monkeypatch.setattr(auth, "start", start)
    monkeypatch.setattr(auth, "poll_once", server.poll_once)
    monkeypatch.setattr(yoke_token_verify, "verify", verify)
    monkeypatch.setattr(setup_release_start, "_served_release", lambda _: "")
    monkeypatch.setattr(
        team_server_authorization, "browser_sign_in_available", lambda _: False
    )
    flags = (
        "--connect", ORIGIN, "--project-mode", "local-checkout", "--checkout", str(checkout)
    )
    if alias:
        flags += ("--env", alias)

    code, lines = drive(flags=flags)
    assert (code, lines[-1]["key"]) == (0, "connect.team_server_url")
    drive(f"connect.team_server_url={ORIGIN}")
    _only_browser(drive("connect.machine_admission=own"))
    server.polls = [auth.HostedMachineCredential(api_url=ORIGIN, org=ORG, token=TOKEN)]
    code, lines = drive()
    assert (code, lines[-1]["key"]) == (0, "github.machine"), lines[-1]
    expected_env = alias or ORG
    saved = machine_config.active_connection()
    assert (saved["env"], saved["api_url"]) == (expected_env, ORIGIN)
    config = machine_config.load_config()
    assert set(config["connections"]) == {expected_env}
    token_file = Path(saved["credential_source"]["path"])
    assert token_file.read_text().strip() == TOKEN

    walk_to_review(drive, {})
    code, lines = drive("review.confirm=apply")
    assert (code, lines[-1]["state"]) == (0, "done"), lines[-1]
    [applied] = fake.applied
    assert applied["env_name"] == expected_env
    assert applied["api_url"] == ORIGIN
    assert Path(applied["token_file"]) == token_file
    assert Path(applied["project_checkout"]) == checkout
    assert server.started == ["CODE-1"]
    assert len(verified) >= 2
