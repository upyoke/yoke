"""Health-check step runner: readiness plus an exact-candidate build assertion."""

from __future__ import annotations

import sys
import uuid as _uuid
from typing import Any, Dict

from yoke_core.domain.deploy_cli_manifest_gate import verify_deployed_cli_manifest
from yoke_core.tools import step_runners as _step_runners

# Poll through the container swap window so the gate tolerates the brief
# interval between core-deploy's container-health wait and the edge serving
# the NEW build, without ever passing a stale/failed swap — the build
# assertion still gates every attempt.
HEALTH_CHECK_WARMUP_TIMEOUT_S = 120.0
HEALTH_CHECK_RETRY_INTERVAL_S = 6.0


def dispatch_health_check(
    config: Dict[str, Any],
    project: str,
    environment_name: str,
    *,
    project_repo_path: str = "",
    image_tag: str = "",
    release_lineage: str = "",
) -> tuple[int, str]:
    """Run the health-check step runner with env-resolved URL when omitted.

    Returns ``(exit_code, verified_build)``; ``verified_build`` is populated
    only when a real build assertion actually ran and passed, so a caller
    recording a durable stage receipt never treats bare liveness as observed
    candidate evidence.

    An explicit ``url`` in the stage config is used verbatim (no request-id
    contract assumed for arbitrary endpoints, and no build assertion — a raw
    URL override carries no candidate identity to verify). Without one, the
    URL resolves from the flow's target environment
    (declared ``hosts.api`` URL plus ``health_path``) and the check enforces the Yoke
    core x-request-id echo contract PLUS the build assertion: the response's
    ``build`` must equal the expected tag, so the gate proves the NEW code
    answered — not a stale container that survived a failed swap. When this
    run pins a ``release_lineage``, the expected tag is its immutable
    ``canonical_image_tag`` derivation — the same fixed-width truncation
    core-deploy publishes images under — so a pass proves the server answered
    for THIS exact candidate, not merely whatever the declared branch's HEAD
    happens to be right now. Without a pinned lineage the expectation falls
    back to resolving the declared branch's current HEAD from the repo, and
    without a repo path the expectation cannot be resolved at all; either
    weaker case states so instead of silently asserting nothing.

    The env-resolved check also requires ``schema_ready: true`` in the
    health payload: HTTP liveness plus the right build still says nothing
    about the DB behind the service, and a core over a schema-incomplete
    DB answers 200 while its data routes fail.
    """
    url = str(config.get("url", "") or "")
    if url:
        return _step_runners.exec_health_check(url), ""
    if not environment_name:
        print(
            "Error: health-check stage has no url and the flow references "
            "no target environment to resolve one from",
            file=sys.stderr,
        )
        return 1, ""
    from yoke_core.domain.deploy_environment_settings import (
        DeployEnvironmentError,
        resolve_deploy_environment,
    )

    try:
        env = resolve_deploy_environment(project, environment_name)
    except DeployEnvironmentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1, ""

    expected_build = ""
    if image_tag:
        expected_build = image_tag
        print(
            "exec-health-check: build assertion uses explicit deploy image "
            f"tag {expected_build}",
        )
    elif release_lineage:
        from yoke_core.domain.deploy_image_tag import canonical_image_tag

        expected_build = canonical_image_tag(release_lineage)
        print(
            "exec-health-check: build assertion uses this run's pinned "
            f"candidate {expected_build}",
        )
    elif project_repo_path:
        from yoke_core.domain.deploy_core_container_image import resolve_image_tag
        from yoke_core.domain.deploy_remote import CommandRunner

        try:
            expected_build = resolve_image_tag(
                CommandRunner(),
                project_repo_path,
                "",
                declared_branch=env.git_branch,
            )
        except Exception as exc:
            print(
                "exec-health-check: build assertion skipped — expected tag "
                f"unresolvable from {project_repo_path}: {exc}",
            )
    else:
        print(
            "exec-health-check: build assertion skipped — no project repo "
            "path available to resolve the expected tag",
        )
    rc = _step_runners.exec_health_check(
        env.api_health_url,
        request_id=str(_uuid.uuid4()),
        expected_build=expected_build,
        require_schema_ready=True,
        warmup_timeout=HEALTH_CHECK_WARMUP_TIMEOUT_S,
        retry_interval=HEALTH_CHECK_RETRY_INTERVAL_S,
    )
    if rc != 0:
        return rc, ""
    if env.deploy_namespace == "yoke":
        manifest_gate = verify_deployed_cli_manifest(environment_name)
        print(manifest_gate.message)
        if manifest_gate.checked and not manifest_gate.ok:
            return 1, ""
    return 0, expected_build


__all__ = [
    "HEALTH_CHECK_RETRY_INTERVAL_S",
    "HEALTH_CHECK_WARMUP_TIMEOUT_S",
    "dispatch_health_check",
]
