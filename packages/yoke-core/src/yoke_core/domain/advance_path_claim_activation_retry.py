"""Bounded retry helper for path-claim activation under DB-lock contention.

Sibling to :mod:`yoke_core.domain.advance_path_claim_activation`.
The retry primitive is split into its own module so the parent stays
under the authored-file line cap and so the DB-lock classification
lives next to its retry budget rather than mixed into the activation
orchestration loop.

Contract:

- ``resolve_integration_head_with_retry`` wraps the single
  :func:`yoke_core.domain.path_claims_integration_resolver.resolve_integration_head_with_divergence_check`
  call site that ``_activate_one`` makes today.
- ``IntegrationTargetDiverged`` and ``BoundaryCheckError`` keep the
  existing error contract — those are upstream coordination failures,
  not DB-lock contention, and they surface verbatim through
  :class:`ResolveResult`.
- the connection's operational DB error type (the DB-lock signature) triggers a
  bounded exponential backoff sourced from machine config keys
  ``path_claim_activation_db_lock_retry_initial_ms`` and
  ``path_claim_activation_db_lock_retry_max_attempts``. On budget
  exhaustion the result carries an ``error`` string prefixed with
  :data:`DB_LOCK_ERROR_PREFIX` so the downstream block-kind classifier
  in :mod:`worktree_preflight_steps` can tag the failure as
  ``BLOCK_DB_LOCK`` rather than ``BLOCK_PATH_CLAIM`` — substrate
  friction, not coordination.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from . import db_backend
from yoke_core.domain.path_claims_boundary_git import BoundaryCheckError
from yoke_core.domain.path_claims_integration_resolver import (
    IntegrationTargetDiverged,
    resolve_integration_head_with_divergence_check,
)
from yoke_core.domain.runtime_settings import get_int


DB_LOCK_ERROR_PREFIX = "db-lock:"

DEFAULT_RETRY_INITIAL_MS = 100
DEFAULT_RETRY_MAX_ATTEMPTS = 3

_RETRY_INITIAL_MS_KEY = "path_claim_activation_db_lock_retry_initial_ms"
_RETRY_MAX_ATTEMPTS_KEY = "path_claim_activation_db_lock_retry_max_attempts"


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of one integration-head resolution attempt set.

    ``commit_sha`` is the resolved head when ``error`` is ``None``;
    otherwise ``error`` carries the upstream message (diverged /
    boundary / ``db-lock:`` prefixed for substrate contention).
    ``attempts`` is the number of attempts the retry loop made,
    including the one that succeeded or finally failed.
    """

    commit_sha: Optional[str]
    error: Optional[str]
    diverged: bool
    attempts: int


def _backoff_seconds(attempt_idx: int, initial_ms: int) -> float:
    return (initial_ms * (2 ** attempt_idx)) / 1000.0


def resolve_integration_head_with_retry(
    conn: Any,
    *,
    project_id: str,
    repo_path: str,
    integration_target: str,
    sleep_fn=time.sleep,
) -> ResolveResult:
    """Resolve the integration head with bounded retry on DB lock.

    Diverged / boundary errors short-circuit on the first attempt.
    The connection's operational DB error type triggers exponential backoff sourced
    from config. ``sleep_fn`` is injectable for tests.
    """
    initial_ms = get_int(_RETRY_INITIAL_MS_KEY, DEFAULT_RETRY_INITIAL_MS)
    max_attempts = get_int(_RETRY_MAX_ATTEMPTS_KEY, DEFAULT_RETRY_MAX_ATTEMPTS)
    if max_attempts < 1:
        max_attempts = 1
    attempts = 0
    last_lock_error: Optional[BaseException] = None
    while attempts < max_attempts:
        attempts += 1
        try:
            commit_sha = resolve_integration_head_with_divergence_check(
                conn,
                project_id=project_id,
                repo_path=repo_path,
                integration_target=integration_target,
            )
            return ResolveResult(
                commit_sha=commit_sha, error=None,
                diverged=False, attempts=attempts,
            )
        except IntegrationTargetDiverged as exc:
            return ResolveResult(
                commit_sha=None, error=str(exc),
                diverged=True, attempts=attempts,
            )
        except BoundaryCheckError as exc:
            return ResolveResult(
                commit_sha=None, error=str(exc),
                diverged=False, attempts=attempts,
            )
        except db_backend.operational_error_types(conn) as exc:
            last_lock_error = exc
            if attempts < max_attempts:
                sleep_fn(_backoff_seconds(attempts - 1, initial_ms))
    detail = str(last_lock_error) if last_lock_error else "unknown lock error"
    return ResolveResult(
        commit_sha=None,
        error=f"{DB_LOCK_ERROR_PREFIX}retried {attempts} times: {detail}",
        diverged=False,
        attempts=attempts,
    )


__all__ = [
    "DB_LOCK_ERROR_PREFIX",
    "DEFAULT_RETRY_INITIAL_MS",
    "DEFAULT_RETRY_MAX_ATTEMPTS",
    "ResolveResult",
    "resolve_integration_head_with_retry",
]
