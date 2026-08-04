"""Regression suite for the rehearsal-command parse-and-stat validator.

Fixtures the three observed command shapes — literal ``<worktree>``
placeholder (caught as ``unresolved_placeholder``), wrong-path pytest
invocation (caught as ``missing_path``), and a valid command pair — and
asserts the contract holds against a disposable items-table double. Also
covers the short-circuit paths (profile state != ``declared``,
attestation absent or ``rehearsal_commands`` empty), and asserts the
BLOCK ``Issue`` payload shape. The validator never spawns a subprocess,
never provisions a validation surface, and never touches the control
plane — that isolation holds by construction (no monkeypatch needed to
prove it).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from yoke_core.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)
from yoke_core.domain import attestation_rehearsal_dryrun as dryrun
from yoke_core.domain.attestation_rehearsal_dryrun import (
    ATTESTATION_REHEARSAL_COMMAND_FAILED,
    ValidationOutcome,
    issue_payloads_for_item,
    validate_attestation_rehearsal_commands,
)


_FROZEN_AT = "2026-05-20T17:00:00Z"
# The dry-run validator stat's path-shaped tokens against a repo root.
# Resolving from this test file's location keeps the fixtures portable
# across worktrees, developer machines, and CI checkouts.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _seed_item(
    conn,
    *,
    item_id: int,
    profile: Optional[Dict[str, Any]],
    attestation: Optional[Dict[str, Any]],
    project_id: int = 1,
    project_sequence: Optional[int] = None,
) -> None:
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence, "
        "db_mutation_profile, db_compatibility_attestation) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            item_id,
            project_id,
            item_id if project_sequence is None else project_sequence,
            json.dumps(profile) if profile is not None else None,
            json.dumps(attestation) if attestation is not None else None,
        ),
    )
    conn.commit()


@pytest.fixture
def conn():
    conn = connect_disposable_test_db()
    conn.execute(
        "CREATE TABLE items ("
        "id INTEGER PRIMARY KEY, project_id INTEGER, project_sequence INTEGER, "
        "db_mutation_profile TEXT, db_compatibility_attestation TEXT)"
    )
    conn.execute(
        "CREATE TABLE projects ("
        "id INTEGER PRIMARY KEY, slug TEXT, public_item_prefix TEXT)"
    )
    conn.execute(
        "INSERT INTO projects (id, slug, public_item_prefix) "
        "VALUES (1, 'yoke', 'YOK'), (2, 'buzzer', 'BUZ')"
    )
    conn.commit()
    yield conn
    conn.close()


def _declared_profile() -> Dict[str, Any]:
    return {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply",
        "migration_modules": ["dummy_module"],
    }


def _attestation(rehearsal_commands: List[str]) -> Dict[str, Any]:
    return {
        "frozen_at": _FROZEN_AT,
        "pre_merge_readers_writers": "n/a",
        "invariants": "n/a",
        "rehearsal_commands": list(rehearsal_commands),
        "residual_risk_notes": "n/a",
    }


# ---------------------------------------------------------------------------
# The three live YOK-1800 fixtures
# ---------------------------------------------------------------------------


class TestRehearsalCommandFixtures:
    def test_literal_worktree_placeholder_caught(self, conn) -> None:
        _seed_item(
            conn,
            item_id=1,
            profile=_declared_profile(),
            attestation=_attestation(
                [
                    "python3 -m yoke_core.domain.migration_apply rehearse 1 "
                    "--worktree-path <worktree>/runtime/api/domain",
                ]
            ),
        )
        outcomes = validate_attestation_rehearsal_commands(conn, 1)
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.passed is False
        assert outcome.failure_reason == "unresolved_placeholder"
        assert "<worktree>" in outcome.failure_token

    def test_wrong_pytest_path_caught(self, conn) -> None:
        _seed_item(
            conn,
            item_id=2,
            profile=_declared_profile(),
            attestation=_attestation(
                [
                    f"{sys.executable} -m pytest "
                    "runtime/api/domain/test_path_that_does_not_exist.py -q",
                ]
            ),
        )
        outcomes = validate_attestation_rehearsal_commands(conn, 2)
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.passed is False
        assert outcome.failure_reason == "missing_path"
        assert "test_path_that_does_not_exist.py" in outcome.failure_token

    def test_valid_command_pair_passes(self, conn) -> None:
        _seed_item(
            conn,
            item_id=3,
            profile=_declared_profile(),
            attestation=_attestation(
                [
                    # Valid: existing in-repo test file.
                    f"{sys.executable} -m pytest "
                    "runtime/api/domain/test_attestation_rehearsal_dryrun.py -q",
                    # Valid: inline Python with no path tokens.
                    f'{sys.executable} -c "import sys; sys.exit(0)"',
                ]
            ),
        )
        outcomes = validate_attestation_rehearsal_commands(conn, 3)
        assert len(outcomes) == 2
        assert all(o.passed for o in outcomes)
        assert all(o.failure_reason == "" for o in outcomes)


# ---------------------------------------------------------------------------
# Short-circuit paths (no subprocess, no DB writes, no provisioning)
# ---------------------------------------------------------------------------


class TestShortCircuit:
    def test_profile_state_none_returns_empty(self, conn) -> None:
        _seed_item(
            conn,
            item_id=4,
            profile={"state": "none"},
            attestation=_attestation(
                [
                    f"{sys.executable} -m pytest "
                    "runtime/api/domain/test_does_not_exist.py",
                ]
            ),
        )
        assert validate_attestation_rehearsal_commands(conn, 4) == []

    def test_attestation_absent_returns_empty(self, conn) -> None:
        _seed_item(
            conn,
            item_id=5,
            profile=_declared_profile(),
            attestation=None,
        )
        assert validate_attestation_rehearsal_commands(conn, 5) == []

    def test_frozen_at_missing_returns_empty(self, conn) -> None:
        _seed_item(
            conn,
            item_id=6,
            profile=_declared_profile(),
            attestation={
                "rehearsal_commands": [
                    f"{sys.executable} -m pytest "
                    "runtime/api/domain/test_does_not_exist.py",
                ],
            },
        )
        assert validate_attestation_rehearsal_commands(conn, 6) == []

    def test_empty_rehearsal_commands_returns_empty(self, conn) -> None:
        _seed_item(
            conn,
            item_id=7,
            profile=_declared_profile(),
            attestation=_attestation([]),
        )
        assert validate_attestation_rehearsal_commands(conn, 7) == []

    def test_missing_item_returns_empty(self, conn) -> None:
        assert validate_attestation_rehearsal_commands(conn, 999) == []


# ---------------------------------------------------------------------------
# Issue payload shape
# ---------------------------------------------------------------------------


class TestIssuePayloadShape:
    def test_payload_fields_for_placeholder_failure(self, conn) -> None:
        _seed_item(
            conn,
            item_id=8,
            profile=_declared_profile(),
            attestation=_attestation(
                [
                    "echo <unresolved>/path/to/anything.py",
                ]
            ),
        )
        payloads = issue_payloads_for_item(conn, 8)
        assert len(payloads) == 1
        payload = payloads[0]
        assert payload["code"] == ATTESTATION_REHEARSAL_COMMAND_FAILED
        assert "unresolved placeholder" in payload["message"]
        assert "yoke db-claim amend YOK-8 --reason" in payload["remediation"]
        assert "service_client" not in payload["remediation"]
        context = payload["context"]
        assert context["failure_reason"] == "unresolved_placeholder"
        assert "<unresolved>" in context["failure_token"]
        assert "command" in context

    def test_payload_fields_for_missing_path_failure(self, conn) -> None:
        _seed_item(
            conn,
            item_id=9,
            profile=_declared_profile(),
            attestation=_attestation(
                [
                    f"{sys.executable} -m pytest "
                    "runtime/api/domain/test_does_not_exist.py -q",
                ]
            ),
        )
        payloads = issue_payloads_for_item(conn, 9)
        assert len(payloads) == 1
        assert payloads[0]["context"]["failure_reason"] == "missing_path"
        assert "missing path" in payloads[0]["message"]

    def test_payload_empty_for_all_pass(self, conn) -> None:
        _seed_item(
            conn,
            item_id=10,
            profile=_declared_profile(),
            attestation=_attestation(
                [
                    f"{sys.executable} -c \"print('ok')\"",
                ]
            ),
        )
        assert issue_payloads_for_item(conn, 10) == []


# ---------------------------------------------------------------------------
# By-construction safety: the validator never executes
# ---------------------------------------------------------------------------


class TestNoSubprocessSafety:
    def test_validator_does_not_call_subprocess_run(
        self,
        conn,
        monkeypatch,
    ) -> None:
        """Tripwire on subprocess.run; YOK-1800 broken shape must not execute."""
        sentinel: List[str] = []

        def tripwire(*args, **kwargs):
            sentinel.append("subprocess.run called")
            raise AssertionError(
                "validator must not spawn a subprocess "
                f"(args={args!r}, kwargs={kwargs!r})"
            )

        # Pre-resolve repo root so the validator does not hit git.
        monkeypatch.setattr(dryrun, "_resolve_repo_root", lambda: _REPO_ROOT)
        monkeypatch.setattr(dryrun.subprocess, "run", tripwire)

        _seed_item(
            conn,
            item_id=11,
            profile=_declared_profile(),
            attestation=_attestation(
                [
                    # A command whose worktree placeholder was never
                    # substituted. If the validator executed this, the
                    # tripwire would fire.
                    "python3 -m yoke_core.domain.migration_apply rehearse 11 "
                    "--worktree-path <worktree>/runtime/api/domain",
                ]
            ),
        )
        outcomes = validate_attestation_rehearsal_commands(conn, 11)
        assert sentinel == []
        assert outcomes[0].passed is False
        assert outcomes[0].failure_reason == "unresolved_placeholder"


def test_validation_outcome_dataclass_exposed() -> None:
    """``ValidationOutcome`` must be public so callers can type-hint it."""
    outcome = ValidationOutcome(command="x", passed=True)
    assert outcome.command == "x"
    assert outcome.passed is True
    assert outcome.failure_reason == ""
    assert outcome.failure_token == ""
