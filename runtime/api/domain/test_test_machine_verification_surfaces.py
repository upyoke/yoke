"""Verification reports the SSH route and the Terminal bridge separately."""

from __future__ import annotations

from runtime.api.domain.machine_qa_test_support import make_conn
from yoke_contracts.test_machine_verification_surfaces import (
    SURFACE_FAILED,
    SURFACE_NOT_RUN,
    SURFACE_PASSED,
    verification_surfaces,
)
from yoke_core.domain.machine_qa_capability import (
    replace_test_machine_settings,
    test_machine_detail as read_test_machine_detail,
)
from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
)


MACHINE = "test-mac"


def test_a_failed_bridge_leaves_the_ssh_surface_passed() -> None:
    surfaces = verification_surfaces(
        [
            {"name": "connection", "ok": True, "transport": "ssh"},
            {"name": "terminal_bridge", "ok": False},
        ],
        project="yoke",
        test_machine=MACHINE,
        os="macos",
    )

    assert surfaces["ssh"] == {"status": SURFACE_PASSED, "check": "connection"}
    bridge = surfaces["terminal_bridge"]
    assert bridge["status"] == SURFACE_FAILED
    assert "SSH still works" in bridge["recovery"]
    assert (
        f"yoke test-machine bridge-diagnose --project yoke --test-machine {MACHINE}"
        in bridge["recovery"]
    )


def test_a_failed_transport_reports_the_bridge_as_not_run() -> None:
    surfaces = verification_surfaces(
        [{"name": "connection", "ok": False}],
        project="yoke",
        test_machine=MACHINE,
        os="macos",
    )

    assert surfaces["ssh"]["status"] == SURFACE_FAILED
    assert (
        f"yoke test-machine exec --project yoke --test-machine {MACHINE} -- /usr/bin/true"
        in surfaces["ssh"]["recovery"]
    )
    assert surfaces["terminal_bridge"] == {
        "status": SURFACE_NOT_RUN,
        "check": "terminal_bridge",
    }


def test_the_machine_detail_carries_each_surface_beside_the_overall_status() -> None:
    conn = make_conn()
    replace_test_machine_settings(
        conn,
        project="yoke",
        settings={
            "resource_name": MACHINE,
            "host": "test-mac.example.ts.net",
            "user": "tester",
            "os": "macos",
            "operating_notes": "",
        },
        base_settings=None,
    )
    record_test_machine_verification(
        conn,
        1,
        test_machine=MACHINE,
        status="error",
        checks=[
            {"name": "connection", "ok": True},
            {"name": "terminal_bridge", "ok": False},
        ],
        error_code="terminal_app_control_unavailable",
    )

    verification = read_test_machine_detail(conn, project="yoke", test_machine=MACHINE)[
        "verification"
    ]

    assert verification["status"] == "error"
    assert verification["surfaces"]["ssh"]["status"] == SURFACE_PASSED
    assert verification["surfaces"]["terminal_bridge"]["status"] == SURFACE_FAILED


def test_linux_and_windows_recovery_names_the_xrdp_desktop():
    for os in ("linux", "windows"):
        surfaces = verification_surfaces(
            [{"name": "terminal_bridge", "ok": False}],
            project="yoke", test_machine="lab", os=os,
        )
        recovery = surfaces["terminal_bridge"]["recovery"]
        assert "Terminal.app" not in recovery and "bridge-diagnose" not in recovery
        assert "~/.xsession-errors" in recovery
        assert "/var/log/xrdp-sesman.log" in recovery
        assert "yoke test-machine verify" in recovery
