"""Install persist must send machine_id through the real upsert handler."""

from __future__ import annotations

from pathlib import Path

import json

from yoke_cli.project_install.harness_machine_persist import persist_install_glue
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_contracts.machine_config.runtime import (
    ensure_machine_id,
    machine_id as read_machine_id,
)
from yoke_core.domain import db_helpers, harness_machine_state
from yoke_core.domain.handlers import harness_machine_report


MACHINE = "11111111-1111-4111-8111-111111111111"
PROJECT_ID = 7
REPORT = {
    "harness_id": "cursor",
    "glue_present": True,
    "glue_malformed": False,
    "config_present": True,
    "project_entry_present": False,
    "approval_state": "unknown",
}


class _Connection:
    def close(self) -> None:
        pass


def _patch_inventory(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_cli.project_install.harness_inventory.collect_harness_inventory",
        lambda repo_root: [dict(REPORT)],
    )
    monkeypatch.setattr(
        "yoke_cli.project_install.harness_inventory.collect_pack_prerequisite_inventory",
        lambda repo_root: [],
    )
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.ensure_handlers_loaded",
        lambda: None,
    )


def _dispatch_through_handler(**kwargs):
    request = FunctionCallRequest(
        function=kwargs["function_id"],
        actor=kwargs.get("actor")
        or ActorContext(actor_id="operator", session_id="session-1"),
        target=kwargs["target"],
        payload=kwargs["payload"],
    )
    outcome = harness_machine_report.handle_harness_machine_report_upsert(request)
    return FunctionCallResponse(
        success=outcome.primary_success,
        function=kwargs["function_id"],
        version="v1",
        request_id="req-1",
        result=outcome.result_payload or {},
        error=outcome.error,
    )


def test_install_payload_is_accepted_and_scoped_to_this_machine(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict = {}
    upserts: list[dict] = []

    def fake_upsert(conn, *, project_id, machine_id, reports):
        upserts.append(
            {
                "project_id": project_id,
                "machine_id": machine_id,
                "reports": reports,
            }
        )
        return list(reports)

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return _dispatch_through_handler(**kwargs)

    _patch_inventory(monkeypatch)
    monkeypatch.setattr(
        "yoke_cli.project_install.harness_machine_persist.ensure_machine_id",
        lambda: MACHINE,
    )
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.call_dispatcher",
        fake_dispatch,
    )
    monkeypatch.setattr(db_helpers, "connect", _Connection)
    monkeypatch.setattr(
        harness_machine_state,
        "upsert_harness_machine_reports",
        fake_upsert,
    )

    report: dict = {}
    persist_install_glue(tmp_path, PROJECT_ID, report)

    assert report.get("warnings", []) == []
    payload = captured["payload"]
    assert payload["machine_id"] == MACHINE
    assert payload["project_id"] == PROJECT_ID
    assert payload["reports"][0]["harness_id"] == "cursor"
    assert len(upserts) == 1
    assert upserts[0]["project_id"] == PROJECT_ID
    assert upserts[0]["machine_id"] == MACHINE
    assert upserts[0]["reports"][0]["harness_id"] == "cursor"


def test_install_persist_initializes_stable_machine_id_and_reports(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict = {}
    upserts: list[dict] = []
    home = tmp_path / "yoke-home"
    home.mkdir()
    config = home / "config.json"
    config.write_text(
        json.dumps({"schema_version": 1}, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)

    def fake_upsert(conn, *, project_id, machine_id, reports):
        upserts.append({"project_id": project_id, "machine_id": machine_id})
        return list(reports)

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return _dispatch_through_handler(**kwargs)

    _patch_inventory(monkeypatch)
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.call_dispatcher",
        fake_dispatch,
    )
    monkeypatch.setattr(db_helpers, "connect", _Connection)
    monkeypatch.setattr(
        harness_machine_state,
        "upsert_harness_machine_reports",
        fake_upsert,
    )

    report: dict = {}
    persist_install_glue(tmp_path, PROJECT_ID, report)

    first = captured["payload"]["machine_id"]
    assert report.get("warnings", []) == []
    assert first == read_machine_id()
    assert first == ensure_machine_id()
    assert upserts[0]["machine_id"] == first

    persist_install_glue(tmp_path, PROJECT_ID, report)

    assert captured["payload"]["machine_id"] == first
    assert read_machine_id() == first
    assert {row["machine_id"] for row in upserts} == {first}


def test_install_persist_fail_softs_when_machine_config_is_missing(
    monkeypatch, tmp_path: Path
) -> None:
    dispatched: list[dict] = []

    def fake_dispatch(**kwargs):
        dispatched.append(kwargs)
        raise AssertionError("must not guess a machine and dispatch")

    home = tmp_path / "yoke-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)

    _patch_inventory(monkeypatch)
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.call_dispatcher",
        fake_dispatch,
    )

    report: dict = {}
    persist_install_glue(tmp_path, PROJECT_ID, report)

    assert dispatched == []
    assert report["warnings"]
    assert "not persisted" in report["warnings"][0]
    assert "yoke onboard" in report["warnings"][0]
    assert "upgrade" not in report["warnings"][0].lower()
    assert not (home / "config.json").exists()


def test_install_persist_reuses_existing_machine_id_without_rewriting_config(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict = {}
    home = tmp_path / "yoke-home"
    home.mkdir()
    config = home / "config.json"
    before = json.dumps({"schema_version": 1, "machine_id": MACHINE}, indent=2) + "\n"
    config.write_text(before, encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return _dispatch_through_handler(**kwargs)

    _patch_inventory(monkeypatch)
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.call_dispatcher",
        fake_dispatch,
    )
    monkeypatch.setattr(db_helpers, "connect", _Connection)
    monkeypatch.setattr(
        harness_machine_state,
        "upsert_harness_machine_reports",
        lambda conn, *, project_id, machine_id, reports: list(reports),
    )

    report: dict = {}
    persist_install_glue(tmp_path, PROJECT_ID, report)

    assert report.get("warnings", []) == []
    assert captured["payload"]["machine_id"] == MACHINE
    assert config.read_text(encoding="utf-8") == before
