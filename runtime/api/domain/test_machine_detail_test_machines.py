"""A machine's detail names the Test Machine capability that reaches it."""

from __future__ import annotations

from runtime.api.domain.machine_qa_test_support import make_conn
from yoke_core.domain.handlers.machine_lifecycle import MachineDetailResponse
from yoke_core.domain.machine_detail import _host_label, _test_machines
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings


def _register(conn, test_machine: str, host: str) -> None:
    replace_test_machine_settings(
        conn,
        power_project="yoke",
        test_machine=test_machine,
        settings={
            "resource_name": test_machine,
            "host": host,
            "user": "tester",
            "os": "macos",
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

    linked = _test_machines(conn, {_host_label("Testers-Mac-mini")})

    assert linked == [
        {
            "power_project": "yoke",
            "test_machine": "test-mac",
            "host": "testers-mac-mini.tail0000.ts.net",
            "user": "tester",
            "os": "macos",
            "exec_command": (
                "yoke test-machine exec --test-machine test-mac -- <command>"
            ),
        }
    ]


def test_link_uses_the_universe_host_name() -> None:
    conn = make_conn()
    _register(conn, "test-mac", "testers-mac-mini.tail0000.ts.net")

    assert _test_machines(conn, {"testers-mac-mini"})[0]["test_machine"] == "test-mac"


def test_the_detail_response_carries_the_cross_link() -> None:
    response = MachineDetailResponse(
        machine={},
        harnesses=[],
        projects=[],
        test_machines=[{"test_machine": "test-mac"}],
        running_sessions=[],
        recent_sessions=[],
        recent_launches=[],
        surface_policies=[],
        token={},
        credential_presence={},
    )

    assert response.model_dump()["test_machines"] == [{"test_machine": "test-mac"}]
