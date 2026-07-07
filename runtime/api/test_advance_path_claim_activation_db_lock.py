"""Coverage for the DB-lock classification on path-claim activation.

Covers FR-2: backend operational-error handling in ``_activate_one`` via the
sibling retry helper, bounded exponential
backoff sourced from machine settings, ``BLOCK_DB_LOCK`` block-kind
constant, classifier helper, and the canonical orchestrator narrative
. Also exercises AC-14 (sibling-file split keeps
``advance_path_claim_activation.py`` ≤350 lines) and AC-16 (ordering
safety when activation-time snapshot minting is removed).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.advance_path_claim_activation_retry import (
    DB_LOCK_ERROR_PREFIX,
    DEFAULT_RETRY_INITIAL_MS,
    DEFAULT_RETRY_MAX_ATTEMPTS,
    ResolveResult,
    resolve_integration_head_with_retry,
)
from yoke_core.domain.worktree_preflight_steps import (
    BLOCK_DB_LOCK,
    BLOCK_PATH_CLAIM,
    classify_activation_failure,
    extract_retry_attempts,
)


def _lock_error(conn):
    return db_backend.operational_error_types(conn)[0]("database is locked")


# ---------------------------------------------------------------------------
# resolve_integration_head_with_retry — happy path + lock-retry + exhaustion
# ---------------------------------------------------------------------------


def test_retry_happy_path_no_backoff(monkeypatch):
    """First-attempt success returns ``attempts=1`` and no sleep."""
    sleeps: list[float] = []

    def fake_resolve(*_args, **_kwargs):
        return "deadbeef"

    monkeypatch.setattr(
        "yoke_core.domain.advance_path_claim_activation_retry"
        ".resolve_integration_head_with_divergence_check",
        fake_resolve,
    )
    result = resolve_integration_head_with_retry(
        mock.MagicMock(),
        project_id="yoke", repo_path="/tmp/fake", integration_target="main",
        sleep_fn=sleeps.append,
    )
    assert isinstance(result, ResolveResult)
    assert result.commit_sha == "deadbeef"
    assert result.error is None
    assert result.diverged is False
    assert result.attempts == 1
    assert sleeps == []


def test_retry_recovers_within_budget(monkeypatch):
    sleeps: list[float] = []
    calls = {"n": 0}
    conn = mock.MagicMock()

    def fake_resolve(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _lock_error(conn)
        return "feedface"

    monkeypatch.setattr(
        "yoke_core.domain.advance_path_claim_activation_retry"
        ".resolve_integration_head_with_divergence_check",
        fake_resolve,
    )
    result = resolve_integration_head_with_retry(
        conn,
        project_id="yoke", repo_path="/tmp/fake", integration_target="main",
        sleep_fn=sleeps.append,
    )
    assert result.commit_sha == "feedface"
    assert result.attempts == 3
    # Backoff doubled per attempt: 100ms, 200ms (two retries).
    assert sleeps == [
        DEFAULT_RETRY_INITIAL_MS / 1000.0,
        DEFAULT_RETRY_INITIAL_MS * 2 / 1000.0,
    ]


def test_retry_exhaustion_surfaces_db_lock_prefix(monkeypatch):
    sleeps: list[float] = []
    conn = mock.MagicMock()

    def always_lock(*_args, **_kwargs):
        raise _lock_error(conn)

    monkeypatch.setattr(
        "yoke_core.domain.advance_path_claim_activation_retry"
        ".resolve_integration_head_with_divergence_check",
        always_lock,
    )
    result = resolve_integration_head_with_retry(
        conn,
        project_id="yoke", repo_path="/tmp/fake", integration_target="main",
        sleep_fn=sleeps.append,
    )
    assert result.commit_sha is None
    assert result.diverged is False
    assert result.attempts == DEFAULT_RETRY_MAX_ATTEMPTS
    assert result.error is not None
    assert result.error.startswith(DB_LOCK_ERROR_PREFIX)
    assert f"retried {DEFAULT_RETRY_MAX_ATTEMPTS} times" in result.error
    # max_attempts - 1 sleeps fired (no sleep after the final attempt).
    assert len(sleeps) == DEFAULT_RETRY_MAX_ATTEMPTS - 1


def test_retry_diverged_short_circuits(monkeypatch):
    from yoke_core.domain.path_claims_integration_resolver import (
        IntegrationTargetDiverged,
    )
    sleeps: list[float] = []

    def diverged(*_args, **_kwargs):
        raise IntegrationTargetDiverged(
            "diverged: local 12345 vs upstream 67890",
        )

    monkeypatch.setattr(
        "yoke_core.domain.advance_path_claim_activation_retry"
        ".resolve_integration_head_with_divergence_check",
        diverged,
    )
    result = resolve_integration_head_with_retry(
        mock.MagicMock(),
        project_id="yoke", repo_path="/tmp/fake", integration_target="main",
        sleep_fn=sleeps.append,
    )
    assert result.commit_sha is None
    assert result.diverged is True
    assert result.error is not None
    assert "diverged" in result.error
    assert result.attempts == 1
    assert sleeps == []  # no retry on coordination errors


# ---------------------------------------------------------------------------
# classify_activation_failure / extract_retry_attempts
# ---------------------------------------------------------------------------


def test_classify_activation_failure_db_lock():
    stderr = (
        "BLOCKED: claim 42 activation failed: "
        + DB_LOCK_ERROR_PREFIX
        + "retried 3 times: database is locked"
    )
    assert classify_activation_failure(stderr) == BLOCK_DB_LOCK
    assert extract_retry_attempts(stderr) == 3


def test_classify_activation_failure_path_claim_default():
    stderr = "BLOCKED: claim 99 is blocked by upstream 41"
    assert classify_activation_failure(stderr) == BLOCK_PATH_CLAIM
    assert extract_retry_attempts(stderr) is None


def test_classify_activation_failure_empty_default():
    assert classify_activation_failure("") == BLOCK_PATH_CLAIM
    assert extract_retry_attempts("") is None


# ---------------------------------------------------------------------------
# AC-7 — orchestrator narrative regex (substrate friction, not coordination)
# ---------------------------------------------------------------------------


_AC_7_NARRATIVE_RE = re.compile(
    r"DB lock contention on path-snapshot materialization, "
    r"retried \d+ times — substrate friction, not coordination\."
)


def _build_narrative_from_stderr(stderr: str) -> str:
    """Mirror the orchestrator narrative construction in worktree_preflight.

    Tests against the canonical regex without needing to invoke the
    full preflight orchestrator (which depends on db, git, projects).
    """
    block_kind = classify_activation_failure(stderr)
    if block_kind != BLOCK_DB_LOCK:
        return ""
    attempts = extract_retry_attempts(stderr) or 1
    return (
        f"DB lock contention on path-snapshot materialization, "
        f"retried {attempts} times — substrate friction, not coordination."
    )


def test_ac7_narrative_matches_canonical_regex():
    stderr = "BLOCKED: " + DB_LOCK_ERROR_PREFIX + "retried 7 times: database is locked"
    narrative = _build_narrative_from_stderr(stderr)
    assert _AC_7_NARRATIVE_RE.match(narrative), narrative
    # Retry count interpolates from the stderr.
    assert "retried 7 times" in narrative


def test_ac7_narrative_only_for_db_lock_block_kind():
    """Coordination/diverged failures keep the legacy narrative."""
    stderr = "BLOCKED: claim 12 activation failed: diverged refs"
    narrative = _build_narrative_from_stderr(stderr)
    assert narrative == ""  # not built for non-db-lock block kinds


# ---------------------------------------------------------------------------
# AC-14 — sibling-file split keeps the parent under cap
# ---------------------------------------------------------------------------


def test_advance_path_claim_activation_under_line_cap():
    parent = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "domain"
        / "advance_path_claim_activation.py"
    )
    assert parent.exists()
    line_count = sum(1 for _ in parent.read_text(encoding="utf-8").splitlines())
    assert line_count <= 350, f"parent activation module is {line_count} lines (cap 350)"


def test_sibling_retry_module_present():
    sibling = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "domain"
        / "advance_path_claim_activation_retry.py"
    )
    assert sibling.exists()


# ---------------------------------------------------------------------------
# AC-16 — ordering safety when snapshot minting is removed
# ---------------------------------------------------------------------------


def test_ac16_arm_remains_correct_when_mint_target_no_longer_called(monkeypatch):
    """AC-16: operational-error retry + BLOCK_DB_LOCK classification
    remain correct regardless of whether the snapshot mint is removed
    from activation. The arm is defensive
    cover for any residual path into the integration-head resolver that
    still raises a backend operational error; the classification/narrative survive.
    """
    sleeps: list[float] = []
    conn = mock.MagicMock()

    def lock_then_succeed(*_args, **_kwargs):
        if not sleeps:
            raise _lock_error(conn)
        return "abc"

    monkeypatch.setattr(
        "yoke_core.domain.advance_path_claim_activation_retry"
        ".resolve_integration_head_with_divergence_check",
        lock_then_succeed,
    )
    result = resolve_integration_head_with_retry(
        conn,
        project_id="yoke", repo_path="/tmp/fake", integration_target="main",
        sleep_fn=sleeps.append,
    )
    assert result.commit_sha == "abc"
    assert result.attempts == 2
    assert len(sleeps) == 1
