from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from yoke_cli.packs import prerequisites, runner
from yoke_cli.packs.receipt import load_receipt


DOCKER = {
    "tool": "docker",
    "minimum_version": "20.10.0",
    "probe": {"executable": "docker", "version_args": ["--version"]},
    "install": {
        "darwin": "brew install --cask docker",
        "linux": "curl -fsSL https://get.docker.com | sh",
        "windows": "winget install Docker.DockerDesktop",
    },
}


def _bundle() -> dict[str, object]:
    content = "name: sample\n"
    return {
        "bundle_schema": 2,
        "project_id": 9,
        "project_slug": "sample",
        "pack": "container-runtime",
        "name": "Container Runtime",
        "description": "Docker container runtime.",
        "version": "1.0.0",
        "latest_version": "1.0.0",
        "dependencies": [],
        "prerequisites": [DOCKER],
        "documentation": "docs/packs/container-runtime/README.md",
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
                "path": "compose.yml",
                "content": content,
                "encoding": "utf-8",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "mode": 0o644,
            }
        ],
        "content_digest": hashlib.sha256(b"container-runtime").hexdigest(),
    }


@pytest.fixture
def pack_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_fetch_bundle", lambda *args, **kwargs: _bundle())
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)
    monkeypatch.setattr(runner, "_report_receipt", lambda *args, **kwargs: {})


def test_missing_docker_preview_names_the_tool_and_install_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pack_transport: None,
) -> None:
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: None)
    monkeypatch.setattr(prerequisites, "_SYSTEM", lambda: "Darwin")

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="container-runtime",
        operation="get",
    )

    assert report["applied"] is False
    assert report["refused"] is False
    assert report["unsatisfied_prerequisite_count"] == 1
    [row] = report["prerequisites"]
    assert row["tool"] == "docker"
    assert row["code"] == "pack-prerequisite-missing"
    assert row["install_recipe"] == "brew install --cask docker"


def test_missing_docker_apply_refuses_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pack_transport: None,
) -> None:
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: None)
    monkeypatch.setattr(prerequisites, "_SYSTEM", lambda: "Darwin")

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="container-runtime",
        operation="get",
        apply=True,
    )

    assert report["refused"] is True
    assert report["refusal"] == {
        "code": "pack-prerequisites-unsatisfied",
        "message": "Pack install requires usable local tools: docker",
        "tools": ["docker"],
    }
    assert not (tmp_path / "compose.yml").exists()
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
        pack="container-runtime",
        operation="get",
        apply=True,
        allow_missing_tools=True,
    )

    assert report["applied"] is True
    assert report["allow_missing_tools"] is True
    receipt = load_receipt(tmp_path)
    assert receipt is not None
    assert receipt["packs"]["container-runtime"]["prerequisites"] == [DOCKER]
