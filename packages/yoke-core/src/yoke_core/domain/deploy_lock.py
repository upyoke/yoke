"""One deploy lock per project, required to create or execute a run.

Any box holding an owner-only connection can drive a deployment run, and
nothing used to stop two of them driving the same project at once — two
pipelines racing one environment, or a stage promotion overtaking the
production promotion it was supposed to precede. This module is the gate
that makes that impossible: creating a run and executing one both refuse
unless the calling session holds the project's ``DEPLOY:<slug>``
coordination claim.

The lock is per project rather than per environment on purpose. A release
pair deploys stage and production from one pinned source, so both halves
run under one hold and no second driver slips between them.

The claim itself is an ordinary sticky coordination claim
(:mod:`yoke_core.domain.coordination_claims`): the steering seat acquires
it when it starts driving a pair, releases it when the pair completes, and
a hold stranded by a dead seat is freed by the audited human-only
``yoke coordination-claim release``. Nothing here reclaims it
automatically — a pipeline whose local driver died is still running on
CI, and handing its project to a second driver is the failure the lock
exists to prevent.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from yoke_contracts.coordination_claim_keys import DEPLOY_KEY_PREFIX
from yoke_contracts.coordination_claim_recovery import operator_release_command
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.work_claim_targets import make_deploy_serialization_target

#: Passed as ``session_id`` by a call site that has no session of its own
#: to name and wants the ambient one resolved — what a terminal-driven
#: pipeline has. Distinct from ``None``, which asserts "no session".
AMBIENT_SESSION = "<ambient>"


class DeployLockError(Exception):
    """Base class for a refused deployment-run create or execute."""


class DeployLockNotHeldError(DeployLockError):
    """Raised when the caller holds no deploy lock for the project."""


class DeployLockHeldElsewhereError(DeployLockError):
    """Raised when another session holds the project's deploy lock."""


def deploy_lock_key(project_slug: str) -> str:
    """Return the operator key addressing one project's deploy lock."""
    return f"{DEPLOY_KEY_PREFIX}{project_slug}"


def acquire_command(project_slug: str) -> str:
    """Render the command that takes one project's deploy lock."""
    return (
        f"yoke claims coordination-claim acquire --project {project_slug} "
        f"--key {deploy_lock_key(project_slug)} "
        '--reason "driving the release pair"'
    )


def release_command(project_slug: str) -> str:
    """Render the command that frees a deploy lock this session holds."""
    return (
        f"yoke claims coordination-claim release --project {project_slug} "
        f"--key {deploy_lock_key(project_slug)} "
        '--reason "release pair complete"'
    )


def require_deploy_lock(
    conn: Any,
    project: Union[str, int],
    *,
    session_id: Optional[str],
    operation: str,
) -> CoordinationClaim:
    """Return the caller's deploy claim, or refuse with the recovery step.

    ``operation`` names what is being refused (``deployment_runs.create``,
    ``deployment run execution``) so the message says which surface
    stopped rather than leaving the operator to guess.
    """
    identity = resolve_project(conn, project)
    assert identity is not None
    slug = identity.slug
    claim = active_claim(
        conn, make_deploy_serialization_target(identity.id, slug)
    )
    caller = (session_id or "").strip()

    if claim is None:
        raise DeployLockNotHeldError(
            f"{operation} refused: no session holds the deploy lock "
            f"{deploy_lock_key(slug)} for project {slug!r}. One session "
            "drives a project's deployments at a time, so stage and "
            "production halves of one release pair cannot be overtaken. "
            f"Take it first:\n  {acquire_command(slug)}\n"
            f"Release it when the pair completes:\n  {release_command(slug)}"
            + _session_note(caller)
        )

    if not caller or claim.session_id != caller:
        from yoke_core.domain.coordination_claim_contention import (
            describe_claim_contention,
        )

        contention = describe_claim_contention(conn, claim)
        raise DeployLockHeldElsewhereError(
            f"{operation} refused: the deploy lock {deploy_lock_key(slug)} "
            f"for project {slug!r} is held by session "
            f"{claim.session_id} since {claim.claimed_at} "
            f"(heartbeat {claim.last_heartbeat or 'none'}). Wait for that "
            "release pair to finish, or coordinate with its driver. "
            "Human-only recovery for a stranded hold: "
            f"`{operator_release_command(slug, deploy_lock_key(slug))}`, "
            f"which records a WARN OperatorLeaseRelease. {contention.message}"
            + _session_note(caller)
        )

    return claim


def deploy_lock_refusal(
    project: Union[str, int],
    *,
    operation: str,
    session_id: Optional[str] = AMBIENT_SESSION,
) -> Optional[str]:
    """Return the refusal text for a caller without the lock, else None.

    Opens and closes its own read-only connection so a call site gates in
    three lines. A project that resolves to nothing is not a lock
    failure: the caller's own resolution step reports it as what it is,
    and nothing has been written by then.
    """
    from yoke_core.domain import db_helpers
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    caller = (
        resolve_ambient_session_id()
        if session_id == AMBIENT_SESSION
        else session_id
    )
    conn = db_helpers.connect()
    try:
        require_deploy_lock(
            conn, project, session_id=caller, operation=operation
        )
    except DeployLockError as exc:
        return str(exc)
    except LookupError:
        return None
    finally:
        conn.close()
    return None


def _session_note(caller: str) -> str:
    """Explain the missing half when the caller has no session at all.

    A claim row is session-bound by foreign key, so there is no
    session-less deploy lock to take. The recovery is the same one every
    claim-holding operation names, rendered from the same constant so a
    caller is never taught two different answers to one question.
    """
    if caller:
        return ""
    from yoke_core.domain.session_missing_refusal import (
        TERMINAL_SUPPORTED_PATH,
    )

    return (
        "\nThis process resolved no harness session, and a claim belongs to "
        f"a session. {TERMINAL_SUPPORTED_PATH} An operator driving the "
        "deploy from a plain terminal registers one first — see "
        "`yoke sessions begin --help` — and points $YOKE_SESSION_ID at it "
        "so the acquire and the run share one holder."
    )


__all__ = [
    "AMBIENT_SESSION",
    "DeployLockError",
    "DeployLockHeldElsewhereError",
    "DeployLockNotHeldError",
    "acquire_command",
    "deploy_lock_key",
    "deploy_lock_refusal",
    "release_command",
    "require_deploy_lock",
]
