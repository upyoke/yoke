"""Which deployment a run-bound Browser case is about, and what it serves.

A Browser case attached to a deployment run verifies the deployment that run
made. That is a different question from the one
:mod:`browser_qa_preview_identity` answers: a preview is found by slugifying
a branch under the project's preview domain, while a run's deployment is the
registered environment the run targeted. Asking the preview question about a
production run addresses a host nothing deployed, which is how a succeeded
release ends up unable to have its own visual QA captured.

One source answers what it is serving, and only one can: the environment
itself, asked now, over the project's configured served-revision proof for
persistent targets — the ``health-endpoint`` capability's ``identity_path``
beneath the environment's own registered url, read through
:mod:`served_revision_probe`.

Two stored values look like answers and are not. ``release_lineage`` is the
candidate the run was *asked* to deliver, so reading it as proof would let a
run vouch for itself. A ready ``deployment_stage_receipts`` row is stronger —
something did read the environment back — but it records what was served
*then*, and a persistent environment is mutable and shared: after a later run
replaces production, the earlier run's receipt still says what that run
deployed, while the site now serves something else. Accepting it would let QA
browse the newer deployment and stamp the evidence with the older revision.
Which deployment a run is about comes from durable identity; what that
deployment is serving is only ever a present-tense reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.browser_qa_freshness_outcome import (
    DEPLOYMENT_RECORD_MISSING,
    DEPLOYMENT_TARGET_UNRESOLVED,
    FreshnessFailure,
    IDENTITY_CONFIG_UNREADABLE,
    IDENTITY_PROOF_MALFORMED,
    IDENTITY_PROOF_UNAVAILABLE,
    SHA_MISMATCH,
)
from yoke_core.domain.deployment_target_identity_config import (
    IDENTITY_CAPABILITY,
    IDENTITY_PATH_KEY,
    persistent_identity_path,
)


@dataclass(frozen=True)
class DeploymentUnderTest:
    """The deployment a run-bound Browser case verifies, as the server sees it.

    ``origin`` is the environment's own registered url and nothing else: it
    is the single host authorized both to answer for this environment and to
    be browsed under this run's freshness claim. ``unresolved`` means the run
    itself does not name a deployment to test,
    which is a different answer from "it names one that cannot prove itself".
    """

    environment: str = ""
    origin: str = ""
    identity_path: str = ""
    identity_error: str = ""
    unresolved: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "origin": self.origin,
            "identity_path": self.identity_path,
            "identity_error": self.identity_error,
            "unresolved": self.unresolved,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "DeploymentUnderTest":
        if not isinstance(payload, Mapping):
            return cls(
                unresolved=(
                    "this control plane returned no deployment target for the "
                    "run, so which deployment the case verifies is unknown"
                )
            )
        return cls(
            environment=str(payload.get("environment") or ""),
            origin=str(payload.get("origin") or ""),
            identity_path=str(payload.get("identity_path") or ""),
            identity_error=str(payload.get("identity_error") or ""),
            unresolved=str(payload.get("unresolved") or ""),
        )


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _scalar(row: Any, index: int, key: str) -> Any:
    if row is None:
        return None
    return row[key] if hasattr(row, "keys") else row[index]


def resolve_deployment_under_test(conn: Any, run_id: str) -> DeploymentUnderTest:
    """Resolve the deployment *run_id* targeted, from control-plane authority."""
    marker = _p(conn)
    run = conn.execute(
        "SELECT project_id,target_environment_id FROM deployment_runs "
        f"WHERE id={marker}",
        (str(run_id),),
    ).fetchone()
    if run is None:
        return DeploymentUnderTest(
            unresolved=(
                f"deployment run {run_id!r} is not registered on this control "
                "plane, so it names no deployment to verify"
            )
        )
    environment_id = _scalar(run, 1, "target_environment_id")
    if environment_id in (None, 0):
        return DeploymentUnderTest(
            unresolved=(
                f"deployment run {run_id!r} targets no registered environment, "
                "so there is no deployment for a Browser case to verify; "
                "attach the case to the item whose branch preview it checks, "
                "or run it against a flow that deploys a registered environment"
            )
        )
    environment = conn.execute(
        f"SELECT name,url FROM environments WHERE id={marker}",
        (int(environment_id),),
    ).fetchone()
    if environment is None:
        return DeploymentUnderTest(
            unresolved=(
                f"deployment run {run_id!r} targets environment id "
                f"{int(environment_id)}, which is not registered; register the "
                "environment before running QA against the run"
            )
        )
    name = str(_scalar(environment, 0, "name") or "")
    configured = persistent_identity_path(
        conn, int(_scalar(run, 0, "project_id") or 0)
    )
    return DeploymentUnderTest(
        environment=name,
        origin=str(_scalar(environment, 1, "url") or "").strip(),
        identity_path=configured.path,
        identity_error=configured.error,
    )


def validate_deployment_identity(
    expected_sha: str,
    *,
    target: DeploymentUnderTest,
    fetch: Optional[Callable[[str], object]] = None,
) -> Optional[FreshnessFailure]:
    """Judge whether the run's deployment is serving *expected_sha* NOW.

    Returns ``None`` only when the environment itself said so on this call.
    """
    from yoke_core.domain import browser_qa as _bqa

    if target.unresolved:
        return FreshnessFailure(DEPLOYMENT_TARGET_UNRESOLVED, target.unresolved)

    if target.identity_error:
        return FreshnessFailure(
            IDENTITY_CONFIG_UNREADABLE,
            f"Whether environment {target.environment!r} publishes an identity "
            f"proof could not be determined: {target.identity_error}. That is "
            "unverified, not unconfigured; restore access to the "
            f"{IDENTITY_CAPABILITY} capability and re-run.",
        )

    if not target.origin or not target.identity_path:
        missing = (
            f"environment {target.environment!r} has no registered url"
            if not target.origin
            else (
                f"the project's {IDENTITY_CAPABILITY} capability sets no "
                f"{IDENTITY_PATH_KEY}"
            )
        )
        return FreshnessFailure(
            DEPLOYMENT_RECORD_MISSING,
            f"Environment {target.environment!r} cannot be asked what it is "
            f"serving, because {missing}. A deployment record says what a run "
            "delivered when it ran, which a later release to the same "
            "environment silently outdates, so it is not accepted in place of "
            "asking. Register the environment's url (yoke projects environment "
            "...) and set the served-revision path (yoke projects "
            f"capability-merge-settings <project> {IDENTITY_CAPABILITY} --set "
            f"{IDENTITY_PATH_KEY}=/<path>), then re-run this case.",
        )

    outcome = probe.probe_served_revision(
        target.origin, target.identity_path, expected_sha=expected_sha, fetch=fetch
    )
    if outcome.kind == probe.UNREACHABLE:
        return FreshnessFailure(
            IDENTITY_PROOF_UNAVAILABLE,
            f"Environment {target.environment!r} could not answer at "
            f"{outcome.url}: {outcome.detail}. Nothing here proves what is "
            "deployed, so this is unverified rather than stale; confirm the "
            "environment is up and serving that path.",
        )
    if outcome.kind == probe.MALFORMED:
        return FreshnessFailure(
            IDENTITY_PROOF_MALFORMED,
            f"The environment at {outcome.url} answered with {outcome.detail}, "
            "which is not a full 40-character commit SHA. An abbreviation or a "
            "page is not proof; serve the exact commit identity there.",
        )
    if outcome.kind == probe.MISMATCH:
        return FreshnessFailure(
            SHA_MISMATCH,
            f"The environment at {outcome.url} is serving {outcome.served}, not "
            f"the expected {expected_sha}. This is the commit it reported "
            "about itself just now, so a later release to this environment has "
            "replaced what the run under test deployed; run this case against "
            "the deployment that is actually live.",
        )
    _bqa._log(
        "Freshness check passed against the revision served at "
        f"{outcome.url}: environment={target.environment}, sha={expected_sha}"
    )
    return None


__all__ = [
    "DeploymentUnderTest",
    "resolve_deployment_under_test",
    "validate_deployment_identity",
]
