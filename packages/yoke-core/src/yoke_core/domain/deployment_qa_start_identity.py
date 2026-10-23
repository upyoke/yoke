"""Ask the frozen target what it serves when a deployment QA stage starts.

QA tests whatever is deployed at its destination. A newer build than the
run delivered is normal (a later release took over), so the runner never
refuses on it: before any host reset or human gate it asks the target the
same present-tense question the Browser case check asks, once, and reports
a different served commit on stderr as an observation.

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


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def start_identity_expectation(
    conn: Any, execution: Mapping[str, Any]
) -> Optional[dict[str, Any]]:
    """What the begun execution's persistent target should be serving, or ``None``.

    The subject comes from the execution's own frozen target, so a shared
    item-QA execution (no member item of its own) resolves the same way a
    private one does. ``None`` for a run-preview target: a preview is named
    for its run and never shared, so it has no other deployment to drift to.
    """
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_shared_plans import execution_subject
    from yoke_core.domain.deployment_qa_target_project import target_project
    from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
    from yoke_core.domain.deployment_target_identity_config import (
        persistent_identity_path,
    )

    run_id = str(execution["deployment_run_id"])
    from yoke_core.domain.deployment_qa_takeover_identity import inherited_target

    if inherited_target(conn, run_id, execution.get("execution_target") or {}):
        return None  # Already-admitted QA may observe builds across this takeover.
    try:
        subject = execution_subject(conn, execution, require_active=False)
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
        "expected_sha": run_delivered_sha(conn, run_id, project_id).strip(),
        "project": str(project.get("slug") or ""),
    }


def report_start_identity(
    execution: Mapping[str, Any],
    *,
    run_id: str,
    stage: str,
    fetch: Optional[Callable[[str], object]] = None,
) -> None:
    """Report on stderr what a begun execution's target serves, if it differs.

    Nothing here refuses. A target serving another build than the run
    delivered is observed, not drift; a target that cannot be asked (no
    proof path, unreachable, no delivered commit) is reported as unverified.
    A server that predates this field sends none, and nothing is reported.
    """
    expectation = execution.get(START_IDENTITY_FIELD)
    if not isinstance(expectation, Mapping):
        return
    target = DeploymentUnderTest.from_payload(expectation.get("target"))
    expected = str(expectation.get("expected_sha") or "")
    if not expected and not target.unresolved:
        print(
            f"yoke qa plan run: identity at QA start unverified for run {run_id} "
            f"stage {stage}: the run records no delivered commit for project "
            f"{expectation.get('project')!r}.",
            file=sys.stderr,
        )
        return
    failure = validate_deployment_identity(
        expected,
        target=target,
        project=str(expectation.get("project") or ""),
        fetch=fetch,
    )
    if failure is None:
        return
    if failure.reason == SHA_MISMATCH:
        print(
            f"yoke qa plan run: observed at QA start for run {run_id} stage "
            f"{stage}: {failure.message} QA continues against the deployed "
            "build; each case records the commit it observed.",
            file=sys.stderr,
        )
        return
    print(
        f"yoke qa plan run: identity at QA start unverified for run {run_id} "
        f"stage {stage} ({failure.reason}): {failure.message}",
        file=sys.stderr,
    )


__all__ = [
    "START_IDENTITY_FIELD",
    "report_start_identity",
    "start_identity_expectation",
]
