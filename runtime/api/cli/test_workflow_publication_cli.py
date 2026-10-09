"""CLI publication loads JSON before dispatch and carries append-only intent."""

import json
from yoke_cli.commands.adapters import workflows_publication as cli
from yoke_cli.commands.registry_workflows import WORKFLOW_SUBCOMMAND_REGISTRY


def test_publish_dispatches_complete_definition_and_reason(tmp_path, monkeypatch):
    definition = {"schema_version": 4, "stages": []}
    document = tmp_path / "definition.json"
    document.write_text(json.dumps(definition))
    calls = []
    monkeypatch.setattr(
        cli, "dispatch_and_emit", lambda **kwargs: calls.append(kwargs) or 0
    )
    assert (
        cli.workflows_version_publish(
            [
                "custom",
                "--definition-file",
                str(document),
                "--expected-current-version",
                "7",
                "--keep-current",
                "--reason",
                "Test definition",
            ]
        )
        == 0
    )
    assert calls[0]["function_id"] == "workflows.version.publish"
    assert calls[0]["payload"] == {
        "workflow_id": "custom",
        "definition": definition,
        "expected_current_version": 7,
        "keep_current": True,
        "reason": "Test definition",
    }
    assert (
        WORKFLOW_SUBCOMMAND_REGISTRY[("workflows", "version", "publish")][1]
        is cli.workflows_version_publish
    )


def test_invalid_file_refuses_before_dispatch(tmp_path, monkeypatch, capsys):
    document = tmp_path / "definition.json"
    document.write_text("[]")
    monkeypatch.setattr(
        cli,
        "dispatch_and_emit",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected dispatch")),
    )
    assert (
        cli.workflows_version_publish(
            ["custom", "--definition-file", str(document), "--reason", "New"]
        )
        == 2
    )
    assert "workflow_definition_file_invalid" in capsys.readouterr().err
