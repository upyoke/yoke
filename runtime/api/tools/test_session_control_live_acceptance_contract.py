"""Closed-input and CLI-boundary tests for Fleet live acceptance."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.tools import session_control_live_acceptance_client as client_module
from runtime.api.tools.session_control_live_acceptance_client import YokeCliClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    SCHEMA_VERSION,
    ACCEPTANCE_SURFACE_CELLS,
    AcceptanceContractError,
    parse_candidate_matrix,
    parse_matrix,
    parse_readiness_matrix,
    validate_deployed_release,
    validate_run_id,
)
from runtime.api.tools.test_session_control_live_acceptance_policy_support import (
    CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION,
    require_exact_desktop_active_policy,
)


VERSIONS = {
    "claude-cli": "2.1.238",
    "claude-desktop": "1.32885.1",
    "codex-cli": "0.149.0-alpha.4.3",
    "cursor-cli": "2026.08.11-e8db854",
}


def _matrix() -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "project": "yoke",
        "cells": [
            {
                "surface": surface,
                "expected_version": VERSIONS[surface],
                "mode": mode,
                "acceptance_role": "surface",
                "proof_scope": "registered_session_control_surface",
                "wake_route": "direct",
                **(
                    {"session_id": "claude-desktop-session"}
                    if mode == "identify"
                    else {}
                ),
            }
            for surface, mode in reversed(ACCEPTANCE_SURFACE_CELLS)
        ]
        + [
            {
                "surface": "codex-cli",
                "expected_version": VERSIONS["codex-cli"],
                "mode": "identify",
                "session_id": "broker-target-session",
                "machine_id": "machine-1",
                "acceptance_role": "broker",
                "proof_scope": "registered_broker_wake_route",
                "wake_route": "machine_selected",
                "broker_session_id": "broker-peer-session",
            }
        ],
    }


def test_matrix_requires_every_supported_evidence_cell_and_sorts_it() -> None:
    parsed = parse_matrix(_matrix())

    assert tuple((cell.surface, cell.mode) for cell in parsed.cells[:-1]) == (
        ACCEPTANCE_SURFACE_CELLS
    )
    assert parsed.cells[0].wake_supported is True
    assert parsed.cells[1].wake_supported is False
    assert parsed.cells[2].cell_name.endswith(
        ":registered_session_control_surface:create"
    )
    codex_versions = [
        cell.expected_version for cell in parsed.cells if cell.surface == "codex-cli"
    ]
    assert codex_versions == ["0.149.0-alpha.4.3", "0.149.0-alpha.4.3"]
    assert parsed.cells[-1].acceptance_role == "broker"
    assert parsed.cells[-1].route == "machine_selected"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda raw: raw["cells"].pop(0), "surface_matrix_incomplete"),
        (
            lambda raw: raw["cells"].append(dict(raw["cells"][0])),
            "surface_cell_duplicate",
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
            lambda raw: raw["cells"][2].pop("session_id"),
            "session_id_missing",
        ),
        (
            lambda raw: raw["cells"][0].update(proof_scope="desktop_window"),
            "proof_scope_invalid",
        ),
        (lambda raw: raw["cells"].pop(), "broker_cell_count_invalid"),
        (
            lambda raw: raw["cells"][-1].update(wake_route="direct"),
            "broker_route_selection_required",
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


def test_floor_qualified_version_is_not_a_candidate() -> None:
    raw = _matrix()
    candidate = next(
        cell
        for cell in raw["cells"]
        if cell["surface"] == "claude-desktop" and cell["mode"] == "identify"
    )
    candidate["expected_version"] = CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION
    raw["cells"] = [candidate]

    with pytest.raises(AcceptanceContractError) as raised:
        parse_candidate_matrix(raw)
    assert raised.value.code == "candidate_version_already_proven"


def test_publicly_routed_surface_is_not_a_private_qualification_candidate() -> None:
    raw = _matrix()
    candidate = next(cell for cell in raw["cells"] if cell["surface"] == "claude-cli")
    candidate["expected_version"] = "2.1.241"
    raw["cells"] = [candidate]

    with pytest.raises(AcceptanceContractError) as raised:
        parse_candidate_matrix(raw)

    assert raised.value.code == "candidate_route_not_private"


def test_candidate_matrix_rejects_empty_duplicate_or_already_proven_cells(
    monkeypatch,
) -> None:
    require_exact_desktop_active_policy(monkeypatch)
    raw = _matrix()
    candidate = next(
        cell
        for cell in raw["cells"]
        if cell["surface"] == "claude-desktop" and cell["mode"] == "identify"
    )
    candidate["expected_version"] = CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION
    raw["cells"] = [candidate]
    assert parse_candidate_matrix(raw).cells[0].surface == "claude-desktop"

    for cells, code in (
        ([], "candidate_cells_empty"),
        ([candidate, dict(candidate)], "candidate_cell_duplicate"),
        (
            [{**candidate, "expected_version": "1.32885.1"}],
            "candidate_version_already_proven",
        ),
    ):
        changed = {**raw, "cells": cells}
        with pytest.raises(AcceptanceContractError) as raised:
            parse_candidate_matrix(changed)
        assert raised.value.code == code


def test_readiness_matrix_retains_complete_contract() -> None:
    raw = _matrix()
    for cell in raw["cells"]:
        if cell["surface"] == "claude-cli":
            cell["expected_version"] = "2.1.241"

    parsed = parse_readiness_matrix(raw)

    assert len(parsed.cells) == 5


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
