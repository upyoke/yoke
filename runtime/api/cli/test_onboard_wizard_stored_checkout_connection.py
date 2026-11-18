"""The Project step offers only checkouts saved for the connection chosen."""

import json

from yoke_contracts.machine_config import schema as contract
from yoke_cli.config.local_universe_connection import LOCAL_ENV
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_flows import SETUP_FLOWS, init_setup_state


def _shell(tmp_path, monkeypatch):
    """A wizard whose active `local` connection maps one existing checkout."""
    monkeypatch.delenv("YOKE_ENV", raising=False)
    checkout = tmp_path / "qa-walk"
    checkout.mkdir()
    payload = contract.canonical_example_payload()
    payload["connections"][LOCAL_ENV] = dict(
        payload["connections"]["source-dev-admin"]
    )
    payload["active_env"] = LOCAL_ENV
    payload["connection_projects"] = {
        LOCAL_ENV: [{"checkout": str(checkout), "project_id": 1}]
    }
    config = tmp_path / "config.json"
    config.write_text(json.dumps(payload))
    shell_type = type(
        "FlowShell",
        SETUP_FLOWS,
        {"_goto": lambda self, view: self.views.append(view)},
    )
    shell = object.__new__(shell_type)
    shell.views = []
    init_setup_state(
        shell,
        defaults=WizardDefaults(config_path=str(config)),
        apply_report=lambda _: {},
    )
    return shell, checkout


def test_new_self_host_connection_offers_no_local_checkout(tmp_path, monkeypatch):
    shell, _checkout = _shell(tmp_path, monkeypatch)
    # Host a server here records the new self-host env before Project opens.
    shell.result.env_name = "self-hosted"

    shell._goto_project_mode()

    assert shell.views[-1].prompt.key == "project.mode"
    assert shell._stored_project_checkouts == []


def test_kept_local_connection_offers_its_checkout(tmp_path, monkeypatch):
    shell, checkout = _shell(tmp_path, monkeypatch)
    shell.result.env_name = LOCAL_ENV

    shell._goto_project_mode()

    prompt = shell.views[-1].prompt
    assert prompt.key == "project.stored_checkout"
    assert prompt.choices[0].value == "stored:0"
    assert prompt.choices[0].label == str(checkout)
