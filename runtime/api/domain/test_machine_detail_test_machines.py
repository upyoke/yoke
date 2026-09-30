"""A machine's detail names the Test Mac capability that reaches it."""

from __future__ import annotations

from runtime.api.domain.machine_qa_test_support import make_conn
from yoke_core.domain.handlers.machine_lifecycle import MachineDetailResponse
from yoke_core.domain.machine_detail import _host_label, _test_machines
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings


def _register(conn, machine: str, host: str) -> None:
    replace_test_machine_settings(
        conn,
        project="yoke",
        machine=machine,
        settings={
            "resource_name": machine,
            "host": host,
            "user": "tester",
            "host_kind": "mac-ssh",
            "operating_notes": "",
        },
        base_settings=None,
    )


def test_a_tailnet_host_matches_the_machine_name_by_its_first_label() -> None:
    assert _host_label("Testers-Mac-mini.tail0000.ts.net") == "testers-mac-mini"
    assert _host_label("Testers-Mac-mini") == "testers-mac-mini"


def test_the_capability_whose_host_is_this_machine_is_listed_with_its_route() -> None:
    conn = make_conn()
    _register(conn, "test-mac", "testers-mac-mini.tail0000.ts.net")
    _register(conn, "other-mac", "other-mini.tail0000.ts.net")

    linked = _test_machines(conn, {_host_label("Testers-Mac-mini")}, {1})

    assert linked == [
        {
            "project": "yoke",
            "machine": "test-mac",
            "capability_type": "test-machine:test-mac",
            "host": "testers-mac-mini.tail0000.ts.net",
            "user": "tester",
            "exec_command": (
                "yoke test-machine exec --project yoke --machine test-mac -- <command>"
            ),
        }
    ]


def test_a_capability_in_a_project_the_reader_cannot_see_stays_hidden() -> None:
    conn = make_conn()
    _register(conn, "test-mac", "testers-mac-mini.tail0000.ts.net")

    assert _test_machines(conn, {"testers-mac-mini"}, set()) == []


def test_the_detail_response_carries_the_cross_link() -> None:
    response = MachineDetailResponse(
        machine={},
        harnesses=[],
        projects=[],
        test_machines=[{"machine": "test-mac"}],
        running_sessions=[],
        recent_sessions=[],
        recent_launches=[],
        surface_policies=[],
        token={},
        credential_presence={},
        offers_enforcement_note="",
    )

    assert response.model_dump()["test_machines"] == [{"machine": "test-mac"}]
