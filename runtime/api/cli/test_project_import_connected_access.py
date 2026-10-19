"""``yoke project import`` reads private sources through connected GitHub."""

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import project_onboard as adapter
from yoke_cli.config import project_onboard, project_onboard_clone

IMPORT_ARGS = [
    "https://github.com/acme/private-widgets.git",
    "checkout",
    "--slug",
    "widgets",
    "--name",
    "Widgets",
    "--default-branch",
    "main",
    "--public-item-prefix",
    "WID",
    "--github-adoption",
    "disabled",
    "--dry-run",
]


def _captured_plan(monkeypatch, config: Path):
    captured = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"operation": "project.import", "applied": False}

    monkeypatch.setattr(project_onboard, "import_project", fake_import)
    assert adapter.project_import([*IMPORT_ARGS, "--config", str(config)]) == 0
    return captured["clone"]


def test_connected_machine_clones_through_github_app(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"github": {"web_url": "https://github.example.test"}}),
        encoding="utf-8",
    )

    plan = _captured_plan(monkeypatch, config)

    assert plan.use_machine_github is True
    assert plan.fork_web_url == "https://github.example.test"
    assert project_onboard_clone.machine_token_provider(plan, config) is not None


@pytest.mark.parametrize("payload", [{}, {"github": {}}])
def test_unconnected_machine_clones_anonymously(tmp_path, monkeypatch, payload):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(payload), encoding="utf-8")

    plan = _captured_plan(monkeypatch, config)

    assert plan.use_machine_github is False
    assert plan.fork_web_url == "https://github.com"
    assert project_onboard_clone.machine_token_provider(plan, config) is None


def test_unreadable_machine_config_refuses_with_its_path(
    tmp_path,
    monkeypatch,
    capsys,
):
    config = tmp_path / "config.json"
    config.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        project_onboard,
        "import_project",
        lambda **_: pytest.fail("import must not run on unreadable config"),
    )

    assert adapter.project_import([*IMPORT_ARGS, "--config", str(config)]) == 1

    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert str(config) in err
    assert "Traceback" not in err
