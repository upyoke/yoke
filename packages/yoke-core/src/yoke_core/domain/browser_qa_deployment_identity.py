"""Which deployment a run-bound Browser case is about, and what it serves.

A Browser case attached to a deployment run verifies the deployment that run
made. That is a different question from the one
:mod:`browser_qa_preview_identity` answers: a preview is found by slugifying
a branch under the project's preview domain, while a run's deployment is the
registered environment the run targeted. Asking the preview question about a
production run addresses a host nothing deployed, which is how a succeeded
release ends up unable to have its own visual QA captured.

Two sources can answer, in this order, and neither is the lineage the run
*requested*:

- the durable observation a receipt-producing stage already recorded for
  that environment (``deployment_stage_receipts.observed_release_lineage``),
  which is what the environment answered when the pipeline asked it; and
- the project's configured served-revision proof for persistent targets —
  the ``health-endpoint`` capability's ``identity_path`` beneath the
  environment's own registered url — read live through
  :mod:`served_revision_probe`.

``deployment_runs.release_lineage`` is the candidate the run was asked to
deliver. Reading it as proof would let a run that pinned a commit vouch for
serving it, which is precisely the substitution the observation exists to
prevent, so it is never consulted here.
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
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.served_revision_probe import is_full_revision


@dataclass(frozen=True)
class DeploymentUnderTest:
    """The deployment a run-bound Browser case verifies, as the server sees it.

    ``origin`` is the environment's own registered url and nothing else: it
    is the single host authorized both to answer for this environment and to
    be browsed under this run's freshness claim. ``observed_sha`` is a
    durable observation, empty when no receipt-producing stage recorded one.
    ``unresolved`` means the run itself does not name a deployment to test,
    which is a different answer from "it names one that cannot prove itself".
    """

    environment: str = ""
    origin: str = ""
    identity_path: str = ""
    identity_error: str = ""
    observed_sha: str = ""
    unresolved: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "origin": self.origin,
            "identity_path": self.identity_path,
            "identity_error": self.identity_error,
            "observed_sha": self.observed_sha,
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
            observed_sha=str(payload.get("observed_sha") or ""),
            unresolved=str(payload.get("unresolved") or ""),
        )


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _scalar(row: Any, index: int, key: str) -> Any:
    if row is None:
        return None
    return row[key] if hasattr(row, "keys") else row[index]


def _observed_release_lineage(
    conn: Any, run_id: str, environment: str, pinned_artifact: str
) -> str:
    """The newest ready receipt THIS run recorded for THIS environment.

    Every part of that binding is load-bearing, because a receipt vouches
    only for the dispatch that produced it: another run's attempt, another
    environment's, or one that never reached ``ready`` says nothing about
    this deployment. Only a ``ready`` receipt carries an observation at all
    — the table's own constraint requires a target name and an observed
    lineage for that status.

    When the run pins an artifact identity, a receipt observing a different
    one is a different artifact and is not this run's evidence. Where the run
    pins none, none is required: that is the existing receipt contract, not
    a looser one.
    """
    if not _table_exists(conn, "deployment_stage_receipts"):
        return ""
    marker = _p(conn)
    row = conn.execute(
        "SELECT observed_release_lineage,observed_artifact_identity "
        "FROM deployment_stage_receipts "
        f"WHERE run_id={marker} AND status='ready' "
        f"AND target_kind='persistent_environment' AND target_name={marker} "
        "ORDER BY attempt_number DESC, id DESC LIMIT 1",
        (str(run_id), str(environment)),
    ).fetchone()
    if row is None:
        return ""
    if pinned_artifact:
        observed_artifact = str(
            _scalar(row, 1, "observed_artifact_identity") or ""
        ).strip()
        if observed_artifact != pinned_artifact:
            return ""
    served = str(_scalar(row, 0, "observed_release_lineage") or "").strip()
    # An abbreviation or a label identifies a prefix, not a commit.
    return served if is_full_revision(served) else ""


def resolve_deployment_under_test(conn: Any, run_id: str) -> DeploymentUnderTest:
    """Resolve the deployment *run_id* targeted, from control-plane authority."""
    marker = _p(conn)
    run = conn.execute(
        "SELECT project_id,target_environment_id,artifact_identity "
        f"FROM deployment_runs WHERE id={marker}",
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
        observed_sha=_observed_release_lineage(
            conn,
            str(run_id),
            name,
            str(_scalar(run, 2, "artifact_identity") or "").strip(),
        ),
    )


def validate_deployment_identity(
    run_id: str,
    expected_sha: str,
    *,
    target: DeploymentUnderTest,
    fetch: Optional[Callable[[str], object]] = None,
) -> Optional[FreshnessFailure]:
    """Judge whether the run's deployment is serving *expected_sha*.

    Returns ``None`` when it is proven, logging which source proved it so a
    reader can tell a recorded observation from a live answer.
    """
    from yoke_core.domain import browser_qa as _bqa

    if target.unresolved:
        return FreshnessFailure(DEPLOYMENT_TARGET_UNRESOLVED, target.unresolved)

    if target.observed_sha:
        if target.observed_sha != expected_sha:
            return FreshnessFailure(
                SHA_MISMATCH,
                f"Deployment run {run_id} observed environment "
                f"{target.environment!r} serving {target.observed_sha}, not the "
                f"expected {expected_sha}. This is what the deploying stage "
                "read back from the environment itself; run the case against "
                "the candidate that deployment actually delivered.",
            )
        _bqa._log(
            "Freshness check passed against the deployment stage's recorded "
            f"observation: environment={target.environment}, sha={expected_sha}"
        )
        return None

    if target.identity_error:
        return FreshnessFailure(
            IDENTITY_CONFIG_UNREADABLE,
            f"Deployment run {run_id} recorded no observation for environment "
            f"{target.environment!r}, and whether the project publishes an "
            f"identity proof could not be determined: {target.identity_error}. "
            "That is unverified, not unconfigured; restore access to the "
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
            f"Deployment run {run_id} recorded no observation for environment "
            f"{target.environment!r}, and it cannot be asked what it serves "
            f"because {missing}. Register the environment's url (yoke projects "
            "environment ...) and set the served-revision path (yoke projects "
            f"capability-merge-settings <project> {IDENTITY_CAPABILITY} --set "
            f"{IDENTITY_PATH_KEY}=/<path>), then re-run this case.",
        )

    outcome = probe.probe_served_revision(
        target.origin, target.identity_path, expected_sha=expected_sha, fetch=fetch
    )
    if outcome.kind == probe.UNREACHABLE:
        return FreshnessFailure(
            IDENTITY_PROOF_UNAVAILABLE,
            f"Deployment run {run_id} recorded no observation for environment "
            f"{target.environment!r}, and the environment could not answer at "
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
            f"the expected {expected_sha}. This is the commit it reported about "
            "itself, not a stored record; deploy the expected commit before "
            "running this case.",
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
