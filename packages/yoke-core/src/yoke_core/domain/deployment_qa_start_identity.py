"""Ask the frozen target what it serves before a deployment QA stage starts.

Target occupancy keeps another run from deploying over a server while this
run's QA is open, but a stage can still start on a server that changed
underneath it — a deploy outside any run, or one that predates occupancy.
Walking it anyway costs a host reset, a human gate, and a verdict that has
to be recorded as a failure afterwards. So before the runner resets a test
host or raises a gate, it asks the target the same present-tense question
the Browser freshness check asks per case, once, and a drifted target
refuses in seconds with both builds named.

The server composes the expectation (which origin, which proof path, which
commit) because those are control-plane facts; the runner probes, because
the runner is what reaches the target.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Any, Callable, Optional

from yoke_core.domain.browser_qa_deployment_identity import (
    DeploymentUnderTest,
    validate_deployment_identity,
)
from yoke_core.domain.browser_qa_freshness_outcome import SHA_MISMATCH

#: The begin response field carrying the expectation.
START_IDENTITY_FIELD = "deployment_start_identity"
DRIFT_CODE = "deployment_target_drifted"


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def start_identity_expectation(
    conn: Any, *, run_id: str, stage_name: str, member_item_id: Optional[int]
) -> Optional[dict[str, Any]]:
    """What the stage's persistent target should be serving, or ``None``.

    ``None`` for a run-preview target: a preview is named for its run and
    never shared, so it has no other deployment to drift to.
    """
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_target_project import target_project
    from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
    from yoke_core.domain.deployment_target_identity_config import (
        persistent_identity_path,
    )

    try:
        subject = deployment_qa_stage_subject(
            conn,
            run_id=str(run_id),
            stage_name=stage_name,
            member_item_id=member_item_id,
            require_active=False,
        )
        target = deployment_qa_execution_target(conn, subject)
    except (LookupError, ValueError) as exc:
        # The execution is already begun; an unreadable expectation is
        # reported as unverified rather than failing a committed begin.
        return {"target": {"unresolved": str(exc)}, "expected_sha": "", "project": ""}
    environment = target.get("environment") or {}
    if environment.get("kind") != "persistent_environment":
        return None
    name = str(environment.get("name") or "")
    project = target_project(conn, subject)
    project_id = int(project["id"])
    row = conn.execute(
        f"SELECT url FROM environments WHERE project_id={_p(conn)} AND name={_p(conn)}",
        (project_id, name),
    ).fetchone()
    url = str((row["url"] if hasattr(row, "keys") else row[0]) or "") if row else ""
    configured = persistent_identity_path(conn, project_id, name)
    return {
        "target": DeploymentUnderTest(
            environment=name,
            origin=url.strip(),
            identity_path=configured.path,
            identity_error=configured.error,
        ).as_payload(),
        "expected_sha": run_delivered_sha(conn, str(run_id), project_id).strip(),
        "project": str(project.get("slug") or ""),
    }


def require_start_identity(
    execution: Mapping[str, Any],
    *,
    run_id: str,
    stage: str,
    fetch: Optional[Callable[[str], object]] = None,
) -> Optional[str]:
    """Return the drift refusal for a begun execution, else ``None``.

    Only drift refuses: the target answered with a different build. A
    target that cannot be asked (no proof path, unreachable, no delivered
    commit) is reported on stderr as unverified and left to the per-case
    checks, because refusing there would stop QA for every project that
    publishes no served-revision proof. A server that predates this field
    sends none, and the stage starts as it did before.
    """
    expectation = execution.get(START_IDENTITY_FIELD)
    if not isinstance(expectation, Mapping):
        return None
    target = DeploymentUnderTest.from_payload(expectation.get("target"))
    expected = str(expectation.get("expected_sha") or "")
    if not expected and not target.unresolved:
        print(
            f"yoke qa plan run: identity at QA start unverified for run {run_id} "
            f"stage {stage}: the run records no delivered commit for project "
            f"{expectation.get('project')!r}.",
            file=sys.stderr,
        )
        return None
    failure = validate_deployment_identity(
        expected,
        target=target,
        project=str(expectation.get("project") or ""),
        fetch=fetch,
    )
    if failure is None:
        return None
    if failure.reason != SHA_MISMATCH:
        print(
            f"yoke qa plan run: identity at QA start unverified for run {run_id} "
            f"stage {stage} ({failure.reason}): {failure.message}",
            file=sys.stderr,
        )
        return None
    return (
        f"{DRIFT_CODE}: QA stage {stage} of run {run_id} did not start. "
        f"{failure.message} No host was reset and no gate was raised. "
        "Recovery: redeliver the candidate to this environment (a new run "
        "for the same members), or record this stage's outcome against the "
        "build the environment actually serves."
    )


__all__ = [
    "DRIFT_CODE",
    "START_IDENTITY_FIELD",
    "require_start_identity",
    "start_identity_expectation",
]
