"""Closed-input and CLI-boundary tests for Fleet live acceptance."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.tools import session_control_live_acceptance_client as client_module
from runtime.api.tools.session_control_live_acceptance_client import YokeCliClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    ACCEPTANCE_SURFACES,
    AcceptanceContractError,
    parse_candidate_matrix,
    parse_matrix,
    parse_readiness_matrix,
    validate_deployed_release,
    validate_run_id,
)


VERSIONS = {
    "claude-cli": "2.1.238",
    "claude-desktop": "1.32885.1",
    "codex-cli": "0.148.0-alpha.15",
    "codex-desktop": "26.814.41407",
    "cursor-cli": "2026.08.11-e8db854",
}


def _matrix() -> dict:
    return {
        "schema": 2,
        "project": "yoke",
        "cells": [
            {
                "surface": surface,
                "expected_version": VERSIONS[surface],
                "mode": "identify" if surface == "claude-desktop" else "create",
                "acceptance_role": "surface",
                "wake_route": "none" if surface == "claude-desktop" else "direct",
                **(
                    {"session_id": "claude-desktop-session"}
                    if surface == "claude-desktop"
                    else {}
                ),
            }
            for surface in reversed(ACCEPTANCE_SURFACES)
        ]
        + [
            {
                "surface": "codex-cli",
                "expected_version": VERSIONS["codex-cli"],
                "mode": "identify",
                "session_id": "broker-target-session",
                "machine_id": "machine-1",
                "acceptance_role": "broker",
                "wake_route": "broker",
                "broker_session_id": "broker-peer-session",
            }
        ],
    }


def test_matrix_requires_every_supported_evidence_cell_and_sorts_it() -> None:
    parsed = parse_matrix(_matrix())

    assert parsed.project == "yoke"
    assert tuple(cell.surface for cell in parsed.cells[:-1]) == ACCEPTANCE_SURFACES
    assert parsed.cells[0].wake_supported is True
    assert parsed.cells[1].wake_supported is False
    assert parsed.cells[-1].acceptance_role == "broker"
    assert parsed.cells[-1].route == "broker"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda raw: raw["cells"].pop(0), "surface_matrix_incomplete"),
        (
            lambda raw: raw["cells"].append(dict(raw["cells"][0])),
            "surface_duplicate",
        ),
        (
            lambda raw: raw["cells"][0].update(extra="not-allowed"),
            "cell_shape_invalid",
        ),
        (
            lambda raw: raw["cells"][0].update(expected_version="unknown"),
            "expected_version_unproven",
        ),
        (
            lambda raw: raw["cells"][0].update(surface="cursor-desktop"),
            "surface_unsupported",
        ),
        (
            lambda raw: raw["cells"][3].update(mode="create", session_id=None),
            "create_unproven",
        ),
        (
            lambda raw: raw["cells"][3].pop("session_id"),
            "session_id_missing",
        ),
        (lambda raw: raw["cells"].pop(), "broker_cell_count_invalid"),
        (
            lambda raw: raw["cells"][-1].update(wake_route="direct"),
            "broker_wake_route_required",
        ),
        (
            lambda raw: raw["cells"][-1].update(mode="create", session_id=None),
            "broker_identify_required",
        ),
        (
            lambda raw: raw["cells"][-1].update(
                broker_session_id="broker-target-session"
            ),
            "broker_target_same_session",
        ),
    ],
)
def test_matrix_refuses_unpinned_or_incomplete_evidence(mutation, code) -> None:
    raw = _matrix()
    mutation(raw)

    with pytest.raises(AcceptanceContractError) as raised:
        parse_matrix(raw)

    assert raised.value.code == code


def test_candidate_matrix_preserves_shape_but_defers_private_version_proof() -> None:
    raw = _matrix()
    versions = {"claude-cli": "2.1.241", "claude-desktop": "1.34493.1"}
    for cell in raw["cells"]:
        if cell["surface"] in versions:
            cell["expected_version"] = versions[cell["surface"]]
    raw["cells"] = [
        cell
        for cell in raw["cells"]
        if cell["acceptance_role"] == "surface" and cell["surface"] in versions
    ]

    candidate = parse_candidate_matrix(raw)

    assert candidate.cells[0].expected_version == "2.1.241"
    assert candidate.cells[1].expected_version == "1.34493.1"
    with pytest.raises(AcceptanceContractError) as raised:
        parse_matrix(raw)
    assert raised.value.code == "expected_version_unproven"


def test_candidate_matrix_rejects_empty_duplicate_or_already_proven_cells() -> None:
    raw = _matrix()
    candidate = next(cell for cell in raw["cells"] if cell["surface"] == "claude-cli")
    candidate["expected_version"] = "2.1.241"
    raw["cells"] = [candidate]
    assert parse_candidate_matrix(raw).cells[0].surface == "claude-cli"

    for cells, code in (
        ([], "candidate_cells_empty"),
        ([candidate, dict(candidate)], "candidate_cell_duplicate"),
        (
            [{**candidate, "expected_version": "2.1.238"}],
            "candidate_version_already_proven",
        ),
    ):
        changed = {**raw, "cells": cells}
        with pytest.raises(AcceptanceContractError) as raised:
            parse_candidate_matrix(changed)
        assert raised.value.code == code


def test_candidate_matrix_keeps_surface_before_broker_for_same_surface() -> None:
    surface = {
        "surface": "claude-cli",
        "expected_version": "2.1.241",
        "mode": "create",
        "acceptance_role": "surface",
        "wake_route": "direct",
    }
    broker = {
        **surface,
        "mode": "identify",
        "session_id": "broker-target",
        "machine_id": "machine-1",
        "acceptance_role": "broker",
        "wake_route": "broker",
        "broker_session_id": "broker-peer",
    }

    parsed = parse_candidate_matrix(
        {"schema": 2, "project": "yoke", "cells": [broker, surface]}
    )

    assert tuple(cell.acceptance_role for cell in parsed.cells) == (
        "surface",
        "broker",
    )


def test_readiness_matrix_retains_complete_deferred_contract() -> None:
    raw = _matrix()
    for cell in raw["cells"]:
        if cell["surface"] == "claude-cli":
            cell["expected_version"] = "2.1.241"

    parsed = parse_readiness_matrix(raw)

    assert len(parsed.cells) == 6


def test_run_id_is_bounded_for_repeatable_idempotency_keys() -> None:
    assert validate_run_id("release-20260823.1") == "release-20260823.1"
    for value in ("", "has spaces", "x" * 65, ":starts-with-colon"):
        with pytest.raises(AcceptanceContractError) as raised:
            validate_run_id(value)
        assert raised.value.code == "run_id_invalid"


def test_deployed_release_requires_the_exact_full_commit() -> None:
    release = "a" * 40
    assert validate_deployed_release(release, release) == (release, release)
    for expected, observed, code in (
        ("short", release, "release_sha_invalid"),
        (release, "unknown", "server_build_unresolved"),
        (release, "b" * 40, "deployed_release_mismatch"),
        (release, "a" * 12, "server_build_unresolved"),
    ):
        with pytest.raises(AcceptanceContractError) as raised:
            validate_deployed_release(expected, observed)
        assert raised.value.code == code


def test_cli_keeps_message_body_out_of_argv(monkeypatch) -> None:
    captured = {}
    envelope = {
        "success": True,
        "function": "session_control.message.send",
        "version": "v1",
        "result": {"message_id": "message-1"},
    }

    def _run(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps(envelope), stderr="")

    monkeypatch.setattr(client_module.subprocess, "run", _run)
    secret = "body-value-never-in-argv"

    result = YokeCliClient().call(
        ["say", "--stdin", "--session", "session-1"], stdin=secret
    )

    assert result == {"message_id": "message-1"}
    assert captured["argv"][-1] == "--json"
    assert secret not in captured["argv"]
    assert captured["input"] == secret


def test_cli_pins_every_candidate_call_to_the_selected_environment(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _run(argv, **_kwargs):
        calls.append(list(argv))
        if "status" in argv:
            payload = {
                "server": {
                    "reachable": True,
                    "build": "a" * 40,
                    "engine_version": "0.1.1",
                }
            }
        else:
            payload = {"success": True, "result": {"rows": []}}
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(client_module.subprocess, "run", _run)
    client = YokeCliClient(explicit_env="stage")

    client.deployed_release()
    client.call(["sessions", "list"])
    client.call(["session-control", "qualification", "open"])

    assert calls
    assert all(argv[:3] == ["yoke", "--env", "stage"] for argv in calls)


def test_cli_refuses_caller_spoof_and_never_reflects_raw_failure(monkeypatch) -> None:
    for forbidden in (
        ["messages", "get", "m1", "--session-id", "parent"],
        ["messages", "get", "m1", "--env=prod"],
    ):
        with pytest.raises(AcceptanceContractError) as spoofed:
            YokeCliClient().call(forbidden)
        assert spoofed.value.code == "caller_override_forbidden"

    envelope = {
        "success": False,
        "function": "session_control.message.get",
        "version": "v1",
        "result": {},
        "error": {"code": "permission_denied", "message": "SECRET RAW DETAIL"},
    }
    monkeypatch.setattr(
        client_module.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=1,
            stdout=json.dumps(envelope),
            stderr="ANOTHER SECRET",
        ),
    )

    with pytest.raises(AcceptanceContractError) as failed:
        YokeCliClient().call(["messages", "get", "m1"])

    assert failed.value.code == "permission_denied"
    assert "SECRET" not in str(failed.value)


def test_status_boundary_returns_release_identity_only(monkeypatch) -> None:
    status = {
        "server": {
            "reachable": True,
            "build": "a" * 12,
            "engine_version": "0.1.1+launch.999",
            "token_name": "MUST-NOT-RETURN",
        },
        "connection": {"credential_source": "MUST-NOT-RETURN"},
    }
    monkeypatch.setattr(
        client_module.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=0, stdout=json.dumps(status), stderr=""
        ),
    )

    result = YokeCliClient().deployed_release()

    assert result == {
        "server_build": "a" * 12,
        "engine_version": "0.1.1+launch.999",
    }
    assert "MUST-NOT-RETURN" not in json.dumps(result)
