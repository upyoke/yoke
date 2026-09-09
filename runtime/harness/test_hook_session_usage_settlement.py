"""Usage persistence stays independent from hook registration and telemetry."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from yoke_contracts.session_usage_facts import ModelUsage, SessionUsage, usage_document
from yoke_core.hooks import hook_registration_tail, run_tail, telemetry


def _measured(*, input_tokens: int = 11) -> str:
    return usage_document(
        SessionUsage(
            status="complete",
            observed_at="2026-09-09T02:22:39Z",
            source="native-test",
            models=(
                ModelUsage(
                    model="gpt-test",
                    input=input_tokens,
                    cached_input=7,
                    output=5,
                    reasoning=3,
                ),
            ),
        )
    )


@pytest.mark.parametrize("registered", [True, False])
def test_registrar_bool_shape_does_not_supply_executor(
    monkeypatch,
    registered,
):
    calls = []
    monkeypatch.setattr(
        "yoke_core.hooks.registration.ensure_registered_from_hook",
        lambda *_args, **_kwargs: registered,
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_presentation_observation.record_session_presentation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_usage_observation.record_session_usage",
        lambda *_args, **kwargs: calls.append(kwargs),
    )

    hook_registration_tail.apply_hook_session_tail(
        object(),
        ensure_session=("s", "{}", "", True, "", True, False, None, None),
        observed_session=("s", "{}", "codex", True),
    )

    assert calls == [{"session_id": "s", "payload_json": "{}", "executor": "codex"}]


@pytest.mark.parametrize("failure", ["registration", "presentation"])
def test_registration_fact_failures_do_not_suppress_usage(monkeypatch, failure):
    calls = []

    def result(owner):
        if failure == owner:
            raise RuntimeError(f"{owner} unavailable")
        return False

    monkeypatch.setattr(
        "yoke_core.hooks.registration.ensure_registered_from_hook",
        lambda *_args, **_kwargs: result("registration"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_presentation_observation.record_session_presentation",
        lambda *_args, **_kwargs: result("presentation"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_usage_observation.record_session_usage",
        lambda *_args, **kwargs: calls.append(kwargs),
    )

    hook_registration_tail.apply_hook_session_tail(
        object(),
        ensure_session=("s", "{}", "", True, "", True, False, None, None),
        observed_session=("s", "{}", "claude", True),
    )

    assert calls == [{"session_id": "s", "payload_json": "{}", "executor": "claude"}]


@pytest.mark.parametrize("event_name", ["PreToolUse", "Stop", "SessionEnd"])
def test_every_session_hook_builds_usage_without_terminal_registration(event_name):
    context = SimpleNamespace(session_id="s-codex", executor_family="codex")
    request = run_tail._observed_session_request(
        context=context,
        payload={"session_id": "s-codex"},
        stdin_data="{}",
    )

    assert request == ("s-codex", '{"session_id": "s-codex"}', "codex", True)
    ensure = run_tail._ensure_session_request(
        event_name=event_name,
        context=context,
        payload={"session_id": "s-codex"},
        stdin_data="{}",
        controls=None,
        preflight_complete=False,
    )
    assert (ensure is None) is (event_name in {"Stop", "SessionEnd"})


@pytest.mark.parametrize("family", ["claude", "codex"])
def test_runner_context_carries_adapter_family_for_local_usage(family):
    from yoke_core.hooks.context import build_context

    context = build_context(
        event_name="Stop",
        capability=SimpleNamespace(family=family),
        payload={"session_id": "s"},
        remote=False,
    )
    assert context.executor_family == family


def test_direct_cursor_stop_carries_supplied_usage_without_registration():
    carried = _measured()
    context = SimpleNamespace(session_id="s-cursor", executor_family="cursor")
    payload = {"session_id": "s-cursor", "usage_totals": carried}

    request = run_tail._observed_session_request(
        context=context, payload=payload, stdin_data="{}"
    )

    assert json.loads(request[1])["usage_totals"] == carried
    assert request[2] == "cursor"
    assert (
        run_tail._ensure_session_request(
            event_name="Stop",
            context=context,
            payload=payload,
            stdin_data="{}",
            controls=None,
            preflight_complete=False,
        )
        is None
    )


def test_ended_existing_row_accepts_repeated_carried_total_without_revival():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions ("
        "session_id TEXT PRIMARY KEY, usage_totals TEXT, ended_at TEXT)"
    )
    conn.execute("CREATE TABLE work_claims (session_id TEXT, state TEXT)")
    conn.execute(
        "INSERT INTO harness_sessions VALUES (?, ?, ?)",
        ("s-ended", None, "2026-09-09T02:22:39Z"),
    )
    conn.execute("INSERT INTO work_claims VALUES (?, ?)", ("s-ended", "released"))
    carried = _measured()
    observed_session = (
        "s-ended",
        json.dumps({"session_id": "s-ended", "usage_totals": carried}),
        "codex",
        True,
    )

    for _ in range(2):
        hook_registration_tail.apply_hook_session_tail(
            conn,
            ensure_session=None,
            observed_session=observed_session,
        )

    row = conn.execute(
        "SELECT usage_totals, ended_at FROM harness_sessions WHERE session_id = ?",
        ("s-ended",),
    ).fetchone()
    assert row == (carried, "2026-09-09T02:22:39Z")
    assert conn.execute("SELECT * FROM work_claims").fetchall() == [
        ("s-ended", "released")
    ]
    assert conn.total_changes == 3  # two inserts and one repeat-safe usage update


def test_missing_row_is_not_inserted_by_usage_observation():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, usage_totals TEXT)"
    )
    hook_registration_tail.apply_hook_session_tail(
        conn,
        ensure_session=None,
        observed_session=(
            "missing",
            json.dumps({"usage_totals": _measured()}),
            "claude",
            True,
        ),
    )
    assert conn.execute("SELECT * FROM harness_sessions").fetchall() == []


def test_telemetry_failure_does_not_lose_carried_usage(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, usage_totals TEXT)"
    )
    conn.execute("INSERT INTO harness_sessions VALUES (?, ?)", ("s-relay", None))

    @contextmanager
    def existing_connection():
        yield conn

    monkeypatch.setattr(
        "yoke_core.domain.events_writes.hook_emit_connection", existing_connection
    )
    monkeypatch.setattr(
        telemetry,
        "emit_hook_dispatch_telemetry",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("events unavailable")),
    )
    carried = _measured(input_tokens=17)
    telemetry.flush_hook_telemetry(
        [("dispatch", {})],
        observed_session=(
            "s-relay",
            json.dumps({"usage_totals": carried}),
            "codex",
            False,
        ),
    )

    assert conn.execute(
        "SELECT usage_totals FROM harness_sessions WHERE session_id = ?",
        ("s-relay",),
    ).fetchone() == (carried,)


def test_local_reader_uses_trusted_executor_when_registration_skips(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "yoke_harness.usage_attestation.attest_session_usage",
        lambda executor, payload, transcript_path="": (
            seen.append((executor, payload, transcript_path))
            or SessionUsage(
                status="complete",
                source="native-test",
                models=(ModelUsage(model="gpt-test", input=1),),
            )
        ),
    )
    from yoke_core.domain.session_usage_observation import observed_usage_document

    document = observed_usage_document(
        '{"session_id":"s","transcript_path":"/tmp/rollout.jsonl"}',
        "codex",
    )

    assert json.loads(document)["models"][0]["input"] == 1
    assert seen == [
        (
            "codex",
            {"session_id": "s", "transcript_path": "/tmp/rollout.jsonl"},
            "/tmp/rollout.jsonl",
        )
    ]


def test_terminal_tail_consumes_codex_total_written_after_stop_timestamp(
    tmp_path,
    monkeypatch,
):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        json.dumps(
            {
                "timestamp": "2026-09-09T02:22:38.900Z",
                "type": "turn_context",
                "payload": {"model": "gpt-test"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_codex_runtime.codex_transcript_candidates",
        lambda _thread_id: [rollout],
    )
    from yoke_cli.config import machine_config

    monkeypatch.setattr(machine_config, "yoke_home", lambda: tmp_path / "yoke-home")
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, usage_totals TEXT)"
    )
    conn.execute("INSERT INTO harness_sessions VALUES (?, ?)", ("s-late", None))
    context = SimpleNamespace(session_id="s-late", executor_family="codex")
    observed_session = run_tail._observed_session_request(
        context=context,
        payload={"session_id": "s-late", "thread_id": "thread-late"},
        stdin_data="{}",
    )
    hook_registration_tail.apply_hook_session_tail(
        conn, ensure_session=None, observed_session=observed_session
    )
    earlier = conn.execute(
        "SELECT usage_totals FROM harness_sessions WHERE session_id = ?",
        ("s-late",),
    ).fetchone()[0]
    assert json.loads(earlier)["status"] == "unavailable"
    rollout.write_text(
        rollout.read_text(encoding="utf-8")
        + json.dumps(
            {
                "timestamp": "2026-09-09T02:22:39.260Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 29,
                            "cached_input_tokens": 7,
                            "output_tokens": 5,
                            "reasoning_output_tokens": 3,
                        }
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    hook_registration_tail.apply_hook_session_tail(
        conn,
        ensure_session=None,
        observed_session=observed_session,
    )

    stored = conn.execute(
        "SELECT usage_totals FROM harness_sessions WHERE session_id = ?",
        ("s-late",),
    ).fetchone()[0]
    model = json.loads(stored)["models"][0]
    assert (model["input"], model["cached_input"], model["output"]) == (22, 7, 5)
