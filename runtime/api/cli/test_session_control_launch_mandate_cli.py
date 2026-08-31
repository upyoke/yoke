"""CLI contracts for server-composed launch mandates."""

from __future__ import annotations

import io
import sys

from yoke_cli.commands.adapters import session_control_launches as launches


def test_launch_create_omits_stdin_when_composing_the_mandate(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        launches, "dispatch_and_emit", lambda **kwargs: calls.append(kwargs) or 0
    )
    assert (
        launches.session_launch_create(
            [
                "--project",
                "yoke",
                "--surface",
                "cursor-cli",
                "--item",
                "YOK-12",
                "--idempotency-key",
                "compose-1",
            ]
        )
        == 0
    )
    payload = calls[0]["payload"]
    assert payload["instructions"] == ""
    assert "compose_mandate" not in payload
    assert calls[0]["sensitive_values"] == ()


def test_launch_create_raw_instructions_pass_the_full_body(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        launches, "dispatch_and_emit", lambda **kwargs: calls.append(kwargs) or 0
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("Custom full body."))
    assert (
        launches.session_launch_create(
            [
                "--project",
                "yoke",
                "--surface",
                "cursor-cli",
                "--item",
                "YOK-12",
                "--stdin",
                "--raw-instructions",
                "--idempotency-key",
                "raw-1",
            ]
        )
        == 0
    )
    payload = calls[0]["payload"]
    assert payload["instructions"] == "Custom full body."
    assert payload["compose_mandate"] is False
    assert calls[0]["sensitive_values"] == ("Custom full body.",)


def test_launch_create_stdin_without_raw_is_optional_extras(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        launches, "dispatch_and_emit", lambda **kwargs: calls.append(kwargs) or 0
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("Also reopen the failed QA case."))
    assert (
        launches.session_launch_create(
            [
                "--project",
                "yoke",
                "--surface",
                "cursor-cli",
                "--item",
                "YOK-12",
                "--stdin",
                "--idempotency-key",
                "extras-1",
            ]
        )
        == 0
    )
    payload = calls[0]["payload"]
    assert payload["instructions"] == "Also reopen the failed QA case."
    assert "compose_mandate" not in payload
    assert calls[0]["sensitive_values"] == ("Also reopen the failed QA case.",)
