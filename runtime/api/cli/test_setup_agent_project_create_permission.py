"""Agent-mode Review withholds Apply when the person cannot create the project.

A saved hosted sign-in whose ``profile.get`` lists no ``project_create_orgs``
(a project role, no org role) must stop at Review with the named problem,
before Apply makes the project folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config import (
    onboard_preflight,
    onboard_project_create_permission,
    writer,
    yoke_token_verify,
)

pytest.importorskip("textual")

_REAL_PREFLIGHT = onboard_preflight.preflight
TOKEN = "token-never-shown"
API_URL = "https://app.upyoke.com/api/orgs/acme"


def _walk_to_review(tmp_path: Path, monkeypatch, capsys, project_create_orgs):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(onboard_preflight, "preflight", _REAL_PREFLIGHT)
    writer.set_connection(
        "acme",
        transport="https",
        api_url=API_URL,
        token=TOKEN,
        activate=True,
        path=str(machine_config.config_path(None)),
    )
    monkeypatch.setattr(
        yoke_token_verify,
        "verify",
        lambda *_a, **_k: {
            "ok": True,
            "actor": {"label": "Testy"},
            "orgs": [],
            "projects": [{"slug": "yoke"}],
        },
    )
    calls: list[dict] = []

    def _profile(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "result": {"project_create_orgs": project_create_orgs},
        }

    monkeypatch.setattr(onboard_project_create_permission, "call_function", _profile)
    folder = tmp_path / "code" / "demo"
    drive = AgentDriver(capsys)
    _code, lines = drive.walk(
        (
            "project.mode=create-repo",
            "connect.saved_destination=stored",
            "github.machine=skip",
            f"project.folder={folder}",
            "project.details=continue",
            "hosting.provider=skip",
        )
    )
    return drive, fake, folder, calls, lines[-1]


def test_review_blocks_a_new_project_without_project_create(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    drive, fake, folder, calls, review = _walk_to_review(
        tmp_path, monkeypatch, capsys, []
    )

    assert review["key"] == "review.confirm"
    assert review["question"] == "A few things to fix before applying."
    assert review["detail"] == [
        "You lack project.create on this Yoke server's org. Ask a Yoke admin "
        "for an org role that grants it, or choose an existing project."
    ]
    assert "apply" not in [answer["value"] for answer in review["answers"]]
    assert calls and calls[-1]["function"] == "profile.get"
    assert calls[-1]["api_url"] == API_URL

    code, lines = drive("review.confirm=apply")

    assert lines[-1]["key"] == "review.confirm", lines[-1]
    assert fake.applied == []
    assert not folder.exists()


def test_review_offers_apply_when_the_default_org_allows_create(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _drive, _fake, _folder, calls, review = _walk_to_review(
        tmp_path,
        monkeypatch,
        capsys,
        [{"slug": "acme", "name": "Acme", "default": True}],
    )

    assert review["question"] == "Review what Yoke will save."
    assert "apply" in [answer["value"] for answer in review["answers"]]
    assert calls
