"""Run release-run QA controller work on the run's candidate Yoke runtime.

A QA plan's controller-side work -- host-control adapters, mission
preparation, the walker's host commands -- is Yoke code running on the
machine that drives QA. Stage QA runs before production publishes the
candidate to the stable channel, so the machine's installed CLI is usually an
older release and would test the candidate with yesterday's controller.

The server-frozen QA execution target already names everything the
controller needs: the run's candidate source commit
(``deployment.release_lineage``), the installer origin the destination serves
(``endpoints.installer_base_url`` and ``release_channel``) and, for projects
that pin a Yoke release, that ``release_version``. This module derives the
controller contract from those facts, compares it with the running process,
and when they differ hands the begun execution to a disposable candidate
runtime (:mod:`yoke_core.domain.qa_controller_runtime`). It never changes the
machine's channel or installed CLI. A runtime that cannot be provisioned is
refused as ``qa_controller_not_candidate`` before any host lease is taken.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError

#: Set in a handed-off child: the candidate runtime root it runs from.
CONTROLLER_RUNTIME_ENV = "YOKE_QA_CONTROLLER_RUNTIME"
#: Evidence and result key naming the runtime that ran controller work.
CONTROLLER_RUNTIME_KEY = "controller_runtime"
REFUSAL_CODE = "qa_controller_not_candidate"
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class QaControllerNotCandidate(QaPlanExecutionError):
    """The controller cannot run this release-run stage's candidate code."""


class QaControllerStaleTarget(QaControllerNotCandidate):
    """The destination serves another build than the execution's frozen target.

    The owner's begin re-freezes an unbegun execution to the run's current
    target, so the caller retries the begin in place before giving it up.
    """


@dataclass(frozen=True)
class ControllerCandidate:
    """The Yoke runtime a release-run stage's controller work must run."""

    run_id: str
    stage: str
    version: str
    source_commit: str
    installer_base_url: str


@lru_cache(maxsize=1)
def controller_runtime_identity() -> dict[str, Any]:
    """The Yoke build this process runs, recorded in QA evidence."""
    import yoke_core
    from yoke_contracts.engine_version import installed_engine_version
    from yoke_contracts.install_binding import (
        distribution_source_commit_for_module,
        source_checkout_root,
    )

    commit = distribution_source_commit_for_module("yoke-core", yoke_core.__file__)
    kind = "release"
    if not commit:
        root = source_checkout_root(Path(yoke_core.__file__))
        if root is not None:
            commit = _checkout_head(root)
            kind = "source_checkout"
    runtime_root = os.environ.get(CONTROLLER_RUNTIME_ENV, "").strip()
    return {
        "version": installed_engine_version() or "",
        "source_commit": commit,
        "kind": "candidate_runtime" if runtime_root else kind,
        **({"runtime_root": runtime_root} if runtime_root else {}),
    }


def _checkout_head(root: Path) -> str:
    import subprocess

    from yoke_contracts.terminal_detached_process import run

    try:
        completed = run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    head = str(completed.stdout or "").strip()
    return head if completed.returncode == 0 and _FULL_COMMIT.fullmatch(head) else ""


def _fetch_json(url: str, base_url: str) -> dict[str, Any]:
    from yoke_contracts.resilient_fetch import FetchError, fetch_bytes

    try:
        value = json.loads(fetch_bytes(url).body.decode("utf-8"))
    except (FetchError, UnicodeDecodeError, ValueError) as exc:
        raise _resolution_refusal(base_url, f"could not read {url}: {exc}") from exc
    if not isinstance(value, dict):
        raise _resolution_refusal(base_url, f"{url} is not a JSON object")
    return value


def stamp_controller_runtime(evidence: Any) -> Any:
    """``evidence`` with the controller runtime that produced it."""
    if not isinstance(evidence, dict):
        return evidence
    return {**evidence, CONTROLLER_RUNTIME_KEY: controller_runtime_identity()}


def stamp_submission(payload: Mapping[str, Any]) -> None:
    """Record the controller runtime in each submitted Machine case result."""
    for result in payload.get("results") or []:
        if isinstance(result, dict):
            result["evidence"] = stamp_controller_runtime(result.get("evidence") or {})


def _published_source_commit(base_url: str, version: str) -> str:
    url = (
        f"{base_url}/dist/releases/{quote(version, safe='')}/migration-history.json"
    )
    artifact = _fetch_json(url, base_url).get("artifact")
    commit = str((artifact or {}).get("source_commit") or "").strip()
    if not _FULL_COMMIT.fullmatch(commit):
        raise _resolution_refusal(
            base_url, f"{url} names no full source commit for Yoke {version}"
        )
    return commit


def _channel_release(base_url: str, channel: str) -> tuple[str, str]:
    url = f"{base_url}/dist/channels/{quote(channel, safe='')}.json"
    pointer = _fetch_json(url, base_url)
    version = str(pointer.get("version") or "").strip()
    commit = str((pointer.get("migration_history") or {}).get("source_commit") or "")
    if not version or not _FULL_COMMIT.fullmatch(commit):
        raise _resolution_refusal(
            base_url, f"{url} names no version with a full source commit"
        )
    return version, commit


def _resolution_refusal(base_url: str, detail: str) -> QaControllerNotCandidate:
    return QaControllerNotCandidate(
        f"{REFUSAL_CODE}: could not resolve the run candidate's Yoke release at "
        f"{base_url}: {detail}. Restore access to that installer origin, then "
        "re-run the same `yoke qa plan run` command"
    )


def controller_candidate(execution: Mapping[str, Any]) -> ControllerCandidate | None:
    """The candidate runtime a begun release-run execution owes, if any.

    Only a deployment-run execution whose target names an installer origin
    owes one: that origin serves the Yoke release the run delivered (or the
    release its deployed commit pins). Other executions run in-process.
    """
    owner = str(execution.get("deployment_run_id") or "")
    target = execution.get("execution_target")
    if not owner or not isinstance(target, dict):
        return None
    endpoints = target.get("endpoints") or {}
    base_url = str(endpoints.get("installer_base_url") or "").strip().rstrip("/")
    if not base_url:
        return None
    deployment = target.get("deployment") or {}
    # The build is the frozen target's; name the run that delivered it.
    run_id = str(deployment.get("run_id") or owner)
    stage = str(execution.get("deployment_stage") or deployment.get("stage") or "")
    pinned = str(endpoints.get("release_version") or "").strip()
    if pinned:
        version, commit = pinned, _published_source_commit(base_url, pinned)
    else:
        channel = str(endpoints.get("release_channel") or "").strip()
        if not channel:
            raise _resolution_refusal(
                base_url, "the frozen target names neither a release nor a channel"
            )
        version, commit = _channel_release(base_url, channel)
        lineage = str(deployment.get("release_lineage") or "")
        if commit != lineage:
            moved = (
                f" Run {owner} now owns this execution, which still carries run "
                f"{run_id}'s frozen target."
                if owner != run_id
                else ""
            )
            raise QaControllerStaleTarget(
                f"{REFUSAL_CODE}: run {run_id} stage {stage} delivered candidate "
                f"{lineage[:12] or '<none>'}, but {base_url} channel {channel} now "
                f"serves Yoke {version} built from {commit[:12]}.{moved} The "
                "destination no longer serves that candidate; read `yoke "
                f"deployment-runs get {owner}` and run QA on the run that owns the "
                "destination"
            )
    return ControllerCandidate(run_id, stage, version, commit, base_url)


def require_candidate_controller(
    execution: Mapping[str, Any], *, adopted: bool
) -> ControllerCandidate | None:
    """The candidate to hand off to, or ``None`` when this process is it.

    A handed-off child (``adopted``) that still differs refuses rather than
    provisioning again, so a broken runtime can never recurse.
    """
    candidate = controller_candidate(execution)
    if candidate is None:
        return None
    identity = controller_runtime_identity()
    if identity["source_commit"] == candidate.source_commit:
        return None
    if adopted or os.environ.get(CONTROLLER_RUNTIME_ENV):
        raise QaControllerNotCandidate(
            f"{REFUSAL_CODE}: the candidate runtime for run {candidate.run_id} "
            f"runs {identity['source_commit'][:12] or 'an unknown build'}, not "
            f"candidate {candidate.source_commit[:12]}. Delete "
            f"{os.environ.get(CONTROLLER_RUNTIME_ENV) or 'the candidate runtime'} "
            "and re-run the same `yoke qa plan run` command"
        )
    return candidate


#: Re-begins after a stale-target refusal, and the pause before each; the
#: destination's new build can publish moments before its deploy receipt.
RETARGET_ATTEMPTS = 3
RETARGET_WAIT_SECONDS = 20.0


def require_retargeted_candidate(
    execution: Mapping[str, Any],
    *,
    adopted: bool,
    rebegin: Callable[[], Mapping[str, Any]] | None,
) -> tuple[ControllerCandidate | None, Mapping[str, Any]]:
    """The candidate and the execution it holds, re-targeted in place if stale.

    ``rebegin`` repeats the owner's begin, which re-freezes an execution that
    has run nothing to its run's current target, keeping its id and queue
    place. Without it (resume or adoption) a stale target refuses at once.
    """
    for attempt in range(RETARGET_ATTEMPTS + 1):
        try:
            return require_candidate_controller(execution, adopted=adopted), execution
        except QaControllerStaleTarget:
            if rebegin is None or attempt == RETARGET_ATTEMPTS:
                raise
        time.sleep(RETARGET_WAIT_SECONDS)
        again = rebegin()
        if str(again.get("execution_id")) != str(execution.get("execution_id")):
            raise QaPlanExecutionError(
                f"qa_resume_identity_mismatch: re-targeting execution "
                f"{execution.get('execution_id')} returned execution "
                f"{again.get('execution_id')}; preserve both receipts and report "
                "to the control-plane operator"
            )
        execution = again
    raise AssertionError("unreachable")


def not_candidate_refusal(
    candidate: ControllerCandidate, detail: str
) -> QaControllerNotCandidate:
    identity = controller_runtime_identity()
    installed = identity["version"] or "a source checkout"
    commit = identity["source_commit"][:12] or "unknown"
    return QaControllerNotCandidate(
        f"{REFUSAL_CODE}: this controller runs Yoke {installed} ({commit}) but run "
        f"{candidate.run_id} stage {candidate.stage} needs candidate Yoke "
        f"{candidate.version} ({candidate.source_commit[:12]}) from "
        f"{candidate.installer_base_url}, and its disposable runtime could not be "
        f"provisioned: {detail}. No host was leased. Restore access to "
        f"{candidate.installer_base_url}/dist/releases/{candidate.version}/wheels/, "
        "then re-run the same `yoke qa plan run` command; the installed CLI and "
        "its channel were not changed"
    )


__all__ = [
    "CONTROLLER_RUNTIME_ENV",
    "CONTROLLER_RUNTIME_KEY",
    "ControllerCandidate",
    "QaControllerNotCandidate",
    "QaControllerStaleTarget",
    "REFUSAL_CODE",
    "controller_candidate",
    "controller_runtime_identity",
    "not_candidate_refusal",
    "require_candidate_controller",
    "require_retargeted_candidate",
    "stamp_controller_runtime",
    "stamp_submission",
]
