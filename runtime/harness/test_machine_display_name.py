"""Operator-set machine name the relay reports as hostname."""

from __future__ import annotations

from yoke_contracts.machine_config import machine_name as machine_name_module


def test_darwin_prefers_local_host_name_over_the_kernel_host(monkeypatch) -> None:
    monkeypatch.setattr(machine_name_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        machine_name_module,
        "_probe",
        lambda command: (
            "beebauman-macbook-pro-16"
            if command == ("scutil", "--get", "LocalHostName")
            else "ignored-computer-name"
        ),
    )
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "Mac")

    assert machine_name_module.machine_display_name() == "beebauman-macbook-pro-16"


def test_darwin_falls_back_to_computer_name_when_local_host_name_is_unset(
    monkeypatch,
) -> None:
    monkeypatch.setattr(machine_name_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        machine_name_module,
        "_probe",
        lambda command: (
            "Bee MacBook" if command == ("scutil", "--get", "ComputerName") else ""
        ),
    )
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "Mac")

    assert machine_name_module.machine_display_name() == "Bee MacBook"
