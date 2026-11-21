"""Agent setup proposes a free item prefix and refuses a taken one before Apply.

A retired project keeps its prefix, so a second ``qa-nw-accept-*`` project
must not be offered ``QANWAC`` (YOK-5278's walk failed at Apply instead).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config import (
    onboard_preflight,
    onboard_project_create_permission,
    onboard_project_prefixes,
    writer,
    yoke_token_verify,
)

pytest.importorskip("textual")

_REAL_PREFLIGHT = onboard_preflight.preflight
API_URL = "https://app.upyoke.com/api/orgs/acme"
RETIRED = "project 'qa-nw-accept-old' (id 65) (retired)"


def _isolate(tmp_path: Path, monkeypatch, details: dict | None, review: dict):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(onboard_preflight, "preflight", _REAL_PREFLIGHT)
    writer.set_connection(
        "acme",
        transport="https",
        api_url=API_URL,
        token="token-never-shown",
        activate=True,
        path=str(machine_config.config_path(None)),
    )
    monkeypatch.setattr(
        yoke_token_verify,
        "verify",
        lambda *_a, **_k: {"ok": True, "actor": {"label": "Testy"}, "orgs": [],
                           "projects": [{"slug": "yoke"}]},
    )
    monkeypatch.setattr(
        onboard_project_create_permission,
        "call_function",
        lambda **_k: {"success": True, "result": {"project_create_orgs": [
            {"slug": "acme", "name": "Acme", "default": True}]}},
    )
    # The details form and Review each read the holders; answer per reader.
    def _read(*_args):
        at_review = any(f.function == "_review_preflight" for f in inspect.stack())
        return review if at_review else details

    monkeypatch.setattr(onboard_project_prefixes, "read_holders", _read)
    return fake


def _walk_to_details(tmp_path: Path, capsys):
    folder = tmp_path / "code" / "qa-nw-accept-2"
    drive = AgentDriver(capsys)
    _code, lines = drive.walk(
        (
            "project.mode=create-repo",
            "connect.saved_destination=stored",
            "github.machine=skip",
            f"project.folder={folder}",
        )
    )
    return drive, folder, lines[-1]


def _prefix_field(prompt: dict) -> dict:
    return next(
        field for field in prompt["fields"] if field["key"] == "project.details.prefix"
    )


def test_details_propose_a_prefix_no_project_holds(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _isolate(tmp_path, monkeypatch, {"QANWAC": RETIRED}, {"QANWAC": RETIRED})

    drive, _folder, details = _walk_to_details(tmp_path, capsys)

    assert details["key"] == "project.details"
    assert _prefix_field(details)["default"] == "QANWA2"
    _code, lines = drive.walk(("project.details=continue", "hosting.provider=skip"))
    review = lines[-1]
    assert review["key"] == "review.confirm"
    assert "apply" in [answer["value"] for answer in review["answers"]]


def test_details_refuse_a_typed_prefix_another_project_holds(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _isolate(tmp_path, monkeypatch, {"QANWAC": RETIRED}, {"QANWAC": RETIRED})
    drive, _folder, _details = _walk_to_details(tmp_path, capsys)

    _code, lines = drive("project.details.prefix=QANWAC", "project.details=continue")

    assert lines[-1]["key"] == "project.details", lines[-1]
    assert (
        f"Item prefix QANWAC is already used by {RETIRED}. Choose another prefix."
        in str(lines[-1])
    )


def test_review_refuses_a_taken_prefix_the_details_read_missed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    # The details read could not say (None); Review's read names the holder.
    fake = _isolate(tmp_path, monkeypatch, None, {"QANWAC": RETIRED})
    drive, folder, details = _walk_to_details(tmp_path, capsys)
    assert _prefix_field(details)["default"] == "QANWAC"

    _code, lines = drive.walk(("project.details=continue", "hosting.provider=skip"))
    review = lines[-1]

    assert review["key"] == "review.confirm"
    assert review["detail"] == [
        f"Item prefix QANWAC is already used by {RETIRED}. Go back to Project "
        "details and choose another prefix."
    ]
    assert "apply" not in [answer["value"] for answer in review["answers"]]
    _code, lines = drive("review.confirm=apply")
    assert lines[-1]["key"] == "review.confirm", lines[-1]
    assert fake.applied == []
    assert not folder.exists()
