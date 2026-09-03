from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from yoke_cli.packs import prerequisites, runner
from yoke_cli.packs.receipt import load_receipt


PULUMI = {
    "tool": "pulumi",
    "minimum_version": "3.0.0",
    "probe": {"executable": "pulumi", "version_args": ["version"]},
    "install": {
        "darwin": "brew install pulumi/tap/pulumi",
        "linux": "curl -fsSL https://get.pulumi.com | sh",
        "windows": "winget install Pulumi.Pulumi",
    },
}


def _bundle() -> dict[str, object]:
    content = "name: sample\n"
    return {
        "bundle_schema": 2,
        "project_id": 9,
        "project_slug": "sample",
        "pack": "pulumi-foundation",
        "name": "Pulumi Foundation",
        "description": "Pulumi project foundation.",
        "version": "1.0.0",
        "latest_version": "1.0.0",
        "dependencies": [],
        "prerequisites": [PULUMI],
        "documentation": "docs/packs/pulumi-foundation/README.md",
        "settings_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "verification": [{"name": "syntax", "command": "python3 -m compileall"}],
        "render_values": {},
        "files": [
            {
                "path": "Pulumi.yaml",
                "content": content,
                "encoding": "utf-8",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "mode": 0o644,
            }
        ],
        "content_digest": hashlib.sha256(b"pulumi-foundation").hexdigest(),
    }


@pytest.fixture
def pack_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_fetch_bundle", lambda *args, **kwargs: _bundle())
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)
    monkeypatch.setattr(runner, "_report_receipt", lambda *args, **kwargs: {})


def test_missing_pulumi_preview_names_the_tool_and_install_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pack_transport: None,
) -> None:
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: None)
    monkeypatch.setattr(prerequisites, "_SYSTEM", lambda: "Darwin")

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="pulumi-foundation",
        operation="get",
    )

    assert report["applied"] is False
    assert report["refused"] is False
    assert report["unsatisfied_prerequisite_count"] == 1
    [row] = report["prerequisites"]
    assert row["tool"] == "pulumi"
    assert row["code"] == "pack-prerequisite-missing"
    assert row["install_recipe"] == "brew install pulumi/tap/pulumi"


def test_missing_pulumi_apply_refuses_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pack_transport: None,
) -> None:
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: None)
    monkeypatch.setattr(prerequisites, "_SYSTEM", lambda: "Darwin")

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="pulumi-foundation",
        operation="get",
        apply=True,
    )

    assert report["refused"] is True
    assert report["refusal"] == {
        "code": "pack-prerequisites-unsatisfied",
        "message": "Pack install requires usable local tools: pulumi",
        "tools": ["pulumi"],
    }
    assert not (tmp_path / "Pulumi.yaml").exists()
    assert load_receipt(tmp_path) is None


def test_allow_missing_tools_applies_and_records_the_declaration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pack_transport: None,
) -> None:
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: None)

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="pulumi-foundation",
        operation="get",
        apply=True,
        allow_missing_tools=True,
    )

    assert report["applied"] is True
    assert report["allow_missing_tools"] is True
    receipt = load_receipt(tmp_path)
    assert receipt is not None
    assert receipt["packs"]["pulumi-foundation"]["prerequisites"] == [PULUMI]
