"""Image artifact resolution for the core-container deploy executor.

Owns the "make sure the image for this tag exists in the project registry"
half of the deploy: tag resolution from the project repo, registry presence
check, and — when the image is absent — one of two explicit acquisition
modes:

- **build-when-absent** (default; operator machines): build from the exact
  committed tree of the tag and push. Proven local-Docker/Colima path.
- **wait-for-prewarm** (``YOKE_DEPLOY_IMAGE_WAIT=1``; CI): never build —
  poll the registry for the exact-SHA tag the prewarm workflow
  (``.github/workflows/yoke-core-image.yml``) pushes, with a bounded
  budget. GitHub runners lack the buildx/QEMU arm64 setup the prewarm
  workflow carries, so an in-pipeline runner build can never succeed; the
  workflow that invokes the pipeline selects this mode explicitly (no
  ambient CI sniffing).

Either way the registry consumption path downstream is identical, so the
deploy stage itself never cares who produced the artifact.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Callable, Mapping, Optional

from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandResult, CommandRunner

_IMAGE_TAG_LENGTH = 12

# Explicit mode selector: the invoking workflow sets this; operator
# machines never do. Value contract mirrors the codebase env-flag idiom
# (set to the literal "1" to enable).
IMAGE_WAIT_ENV_VAR = "YOKE_DEPLOY_IMAGE_WAIT"
_WAIT_POLL_INTERVAL_S = 30.0
_WAIT_BUDGET_S = 20 * 60


class CoreDeployError(RuntimeError):
    """Deploy preparation failed before/around remote convergence."""


def resolve_image_tag(
    runner: CommandRunner,
    repo_path: str,
    image_tag: str = "",
    *,
    declared_branch: str = "",
) -> str:
    """Return the deploy tag for the target env.

    Precedence: explicit ``image_tag`` (break-glass override) wins over
    everything; an env-declared branch pins the tag to that branch's remote
    HEAD (fetch + FETCH_HEAD — never ambient checkout state); envs with no
    declared branch deploy the repo HEAD short SHA (worktree/SHA deploys,
    the ephemeral tier).
    """
    if image_tag:
        return image_tag
    if not repo_path:
        raise CoreDeployError(
            "[core-deploy] no image_tag provided and no project repo path "
            "available to resolve a deploy SHA"
        )
    if declared_branch:
        fetched = runner.run(
            ["git", "-C", repo_path, "fetch", "origin", declared_branch],
            timeout=120,
        )
        if not fetched.ok:
            raise CoreDeployError(
                f"[core-deploy] could not fetch declared branch "
                f"'{declared_branch}' from origin: {fetched.stderr.strip()}"
            )
        resolved = runner.run(
            ["git", "-C", repo_path, "rev-parse", "FETCH_HEAD"], timeout=30
        )
        if not resolved.ok or not resolved.stdout.strip():
            raise CoreDeployError(
                f"[core-deploy] could not resolve FETCH_HEAD after fetching "
                f"declared branch '{declared_branch}': "
                f"{resolved.stderr.strip()}"
            )
        return resolved.stdout.strip()[:_IMAGE_TAG_LENGTH]
    result = runner.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"], timeout=30
    )
    if not result.ok or not result.stdout.strip():
        raise CoreDeployError(
            f"[core-deploy] could not resolve HEAD of {repo_path}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()[:_IMAGE_TAG_LENGTH]


def _describe_image(
    runner: CommandRunner,
    env: DeployEnvironment,
    aws_env: Mapping[str, str],
    tag: str,
) -> CommandResult:
    """Probe the project registry for ``<repo>:<tag>``."""
    return runner.run(
        [
            "aws", "ecr", "describe-images",
            "--repository-name", env.repository_name,
            "--image-ids", f"imageTag={tag}",
        ],
        env=aws_env,
        timeout=60,
    )


def _wait_for_prewarmed_image(
    runner: CommandRunner,
    env: DeployEnvironment,
    aws_env: Mapping[str, str],
    *,
    tag: str,
    emit: Callable[[str], None],
    budget_s: int,
    poll_interval_s: float,
    sleeper: Callable[[float], None],
) -> str:
    """Poll the registry for the prewarmed tag; never build.

    Raises :class:`CoreDeployError` with operator teaching when the
    budget is exhausted. Attempt-driven so the wait is deterministic:
    ``budget_s // poll_interval_s`` polls, one sleep before each.
    """
    image_ref = env.image_ref(tag)
    max_attempts = max(1, int(budget_s / poll_interval_s))
    emit(
        f"  [core-deploy] image absent; {IMAGE_WAIT_ENV_VAR}=1 — waiting "
        f"for prewarmed {image_ref} (budget {budget_s}s, "
        f"poll every {poll_interval_s:g}s)"
    )
    for attempt in range(1, max_attempts + 1):
        sleeper(poll_interval_s)
        elapsed = int(attempt * poll_interval_s)
        if _describe_image(runner, env, aws_env, tag).ok:
            emit(
                f"  [core-deploy] prewarmed image appeared: {image_ref} "
                f"(attempt {attempt}, {elapsed}s elapsed)"
            )
            return image_ref
        emit(
            f"  [core-deploy] waiting for prewarmed image "
            f"{env.repository_name}:{tag} (attempt {attempt}, "
            f"{elapsed}s elapsed)"
        )
    raise CoreDeployError(
        f"[core-deploy] {IMAGE_WAIT_ENV_VAR}=1 wait exhausted: {image_ref} "
        f"never appeared within {budget_s}s ({max_attempts} polls). CI "
        "deploys never build images — the prewarm workflow "
        "(.github/workflows/yoke-core-image.yml) owns the buildx/QEMU "
        "arm64 build for every push to main/stage; check its run for tag "
        f"{tag} (failed or still running). Once the image exists, re-fire "
        "this deploy via the yoke-env-deploy workflow_dispatch lane (no "
        "new commit — an empty commit mints a NEW sha the prewarm never "
        "built). Deterministic operator fallback (builds locally): run "
        "git -C <source-checkout> fetch origin <target-branch>, resolve "
        "<git-short-sha> from FETCH_HEAD, then YOKE_ENV=<control-plane-env>"
        "-db-admin python3 -m yoke_core.cli.db_router runs create-run "
        f"{env.project} {env.deploy_namespace}-{env.env_name}-release "
        "--created-by operator. Execute the printed run id with "
        "YOKE_ENV=<control-plane-env>-db-admin python3 -m "
        "yoke_core.tools.watch_deploy --product-src <source-checkout> -- "
        "<run-id> --image-tag <git-short-sha>."
    )


def ensure_image_in_registry(
    runner: CommandRunner,
    env: DeployEnvironment,
    aws_env: Mapping[str, str],
    *,
    repo_path: str,
    tag: str,
    emit: Callable[[str], None],
    build_dir: Optional[Path] = None,
    wait_budget_s: int = _WAIT_BUDGET_S,
    wait_poll_interval_s: float = _WAIT_POLL_INTERVAL_S,
    sleeper: Callable[[float], None] = time.sleep,
) -> str:
    """Ensure ``<registry>/<repo>:<tag>`` exists; acquire it when absent.

    Acquisition mode is explicit: with ``YOKE_DEPLOY_IMAGE_WAIT=1`` in
    the process env (set by the CI deploy workflow), wait for the
    prewarmed image with a bounded poll and never build; otherwise build
    from the exact committed tree of the tag and push (operator-machine
    default).
    """
    image_ref = env.image_ref(tag)
    if _describe_image(runner, env, aws_env, tag).ok:
        emit(f"  [core-deploy] image already in registry: {image_ref}")
        return image_ref

    if os.environ.get(IMAGE_WAIT_ENV_VAR, "0") == "1":
        return _wait_for_prewarmed_image(
            runner, env, aws_env, tag=tag, emit=emit,
            budget_s=wait_budget_s, poll_interval_s=wait_poll_interval_s,
            sleeper=sleeper,
        )

    emit(f"  [core-deploy] image absent; building {image_ref} from {tag}")
    if not repo_path:
        raise CoreDeployError(
            "[core-deploy] image is not in the registry and no project repo "
            "path is available to build it"
        )

    if build_dir is None:
        from yoke_core.domain.project_scratch_dir import storage_dir

        build_dir = storage_dir(
            "core-image-build", env.env_name, tag, project=env.project
        )
    build_dir.mkdir(parents=True, exist_ok=True)

    # Build from the exact committed tree of the tag, never the working tree.
    archive = build_dir / "src.tar"
    archived = runner.run(
        [
            "git", "-C", repo_path, "archive", "--format=tar",
            "-o", str(archive), tag,
        ],
        timeout=300,
    )
    if not archived.ok:
        raise CoreDeployError(
            f"[core-deploy] git archive {tag} failed: {archived.stderr.strip()}"
        )
    src_dir = build_dir / "src"
    if src_dir.exists():
        shutil.rmtree(src_dir)
    src_dir.mkdir(parents=True)
    extracted = runner.run(
        ["tar", "-xf", str(archive), "-C", str(src_dir)], timeout=300
    )
    if not extracted.ok:
        raise CoreDeployError(
            f"[core-deploy] source extraction failed: {extracted.stderr.strip()}"
        )

    built = runner.run(
        [
            "docker", "build", "--platform", "linux/arm64",
            "--build-arg", f"YOKE_BUILD_SHA={tag}",
            "-t", image_ref, str(src_dir),
        ],
        timeout=1800,
    )
    if not built.ok:
        raise CoreDeployError(
            "[core-deploy] docker build failed: "
            + (built.stderr or built.stdout).strip()[-1200:]
        )

    login_password = runner.run(
        ["aws", "ecr", "get-login-password"], env=aws_env, timeout=60
    )
    if not login_password.ok or not login_password.stdout.strip():
        raise CoreDeployError(
            "[core-deploy] aws ecr get-login-password failed: "
            + login_password.stderr.strip()
        )
    login = runner.run(
        [
            "docker", "login", "--username", "AWS",
            "--password-stdin", env.registry_host,
        ],
        input_text=login_password.stdout.strip(),
        timeout=60,
    )
    if not login.ok:
        raise CoreDeployError(
            f"[core-deploy] docker login to {env.registry_host} failed: "
            + login.stderr.strip()
        )

    pushed = runner.run(["docker", "push", image_ref], timeout=900)
    if not pushed.ok:
        raise CoreDeployError(
            "[core-deploy] docker push failed: "
            + (pushed.stderr or pushed.stdout).strip()[-1200:]
        )
    emit(f"  [core-deploy] image pushed: {image_ref}")
    return image_ref
