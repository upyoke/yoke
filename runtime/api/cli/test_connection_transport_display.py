"""Human output names the wire scheme; JSON keeps the stored transport."""

import json

import pytest

from yoke_cli.commands.adapters import config as config_adapter
from yoke_cli.config import status_render
from yoke_contracts.machine_config.schema_transport import display_transport
from yoke_core.domain import machine_config_status

HTTP = "http://10.0.0.5:8080"
HTTPS = "https://team.example"


def _connection(api_url: str) -> dict:
    return {
        "env": "team",
        "envs": ["team"],
        "transport": "https",
        "api_url": api_url,
        "credential_source": {"kind": "file"},
    }


@pytest.mark.parametrize("api_url,shown", [(HTTP, "http"), (HTTPS, "https")])
def test_status_renderers_show_the_wire_scheme(api_url, shown):
    report = {"ok": True, "connection": _connection(api_url)}
    for render in (status_render.render_human, machine_config_status.render_human):
        assert f"transport={shown} " in render(report)
    for dumps in (status_render.dumps_json, machine_config_status.dumps_json):
        assert json.loads(dumps(report))["connection"]["transport"] == "https"


def test_connection_list_shows_the_wire_scheme(tmp_path, capsys):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "active_env": "lan",
                "connections": {
                    "lan": {"transport": "https", "api_url": HTTP},
                    "team": {"transport": "https", "api_url": HTTPS},
                },
            }
        )
    )
    assert config_adapter.env_list(["--config", str(config)]) == 0
    table = capsys.readouterr().out
    assert f"lan|true|http|false|{HTTP}" in table
    assert f"team|false|https|false|{HTTPS}" in table
    assert config_adapter.env_list(["--config", str(config), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert {row["transport"] for row in rows} == {"https"}


def test_local_and_missing_transports_pass_through():
    assert display_transport({"transport": "local-postgres"}) == "local-postgres"
    assert display_transport({}) == ""
