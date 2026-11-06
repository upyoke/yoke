"""Trace a failed deployment through relayed GitHub Actions runs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Iterable

from yoke_core.domain.deployment_failure_trace_scoring import (
    _GENERIC_ERRORS,
    clean_lines as _clean_lines,
    terminal_candidate,
    terminal_error,
)

MAX_TRACE_HOPS = 8
_RUN_URL = re.compile(
    r"https://github\.com/(?P<repo>[^/\s]+/[^/\s]+)/actions/runs/(?P<run>\d+)"
)
_FAILED_JOB_ID = re.compile(r"(?:^|\s)X\s+[^\n]*?\(ID\s+(?P<job>\d+)\)")
_RUN_HEADER = re.compile(r"(?:^|\s)[*X]\s+[^\n]*?\s+·\s+(?P<run>\d+)\s*$")
_RELAY_MARKERS = (
    "hosted train concluded failure",
    "observed a downstream failure",
    "downstream run concluded failure",
)


@dataclass(frozen=True)
class RunRef:
    repo: str
    run_id: str
    url: str


@dataclass(frozen=True)
class FailedJob:
    job_id: str
    name: str
    log: str
    log_error: str = ""
    url: str = ""


@dataclass(frozen=True)
class RunSnapshot:
    ref: RunRef
    failed_jobs: tuple[FailedJob, ...]


@dataclass(frozen=True)
class RelaySignal:
    run_refs: tuple[RunRef, ...]
    job_ids: tuple[str, ...]
    observed: bool
    child_not_failed: bool = False


InspectRun = Callable[[RunRef], RunSnapshot]
ResolveJob = Callable[[str, str], RunRef]


def github_run_ref(repo: str, run_id: str) -> RunRef:
    normalized = str(repo or "").strip().strip("/")
    identifier = str(run_id or "").strip()
    return RunRef(
        repo=normalized,
        run_id=identifier,
        url=f"https://github.com/{normalized}/actions/runs/{identifier}",
    )


def _unique_refs(refs: Iterable[RunRef], current: RunRef) -> tuple[RunRef, ...]:
    unique: dict[tuple[str, str], RunRef] = {}
    current_key = (current.repo.casefold(), current.run_id)
    for ref in refs:
        key = (ref.repo.casefold(), ref.run_id)
        if key != current_key:
            unique[key] = ref
    return tuple(unique.values())


def relay_signal(log: str, current: RunRef, *, run_conclusion=None) -> RelaySignal:
    """Identify a downstream-failure relay without treating it as the cause."""
    lines = _clean_lines(log)
    explicit: list[RunRef] = []
    all_refs: list[RunRef] = []
    for line in lines:
        if "stale pair:" in line.casefold():
            continue
        refs = [
            github_run_ref(match.group("repo"), match.group("run"))
            for match in _RUN_URL.finditer(line)
        ]
        all_refs.extend(refs)
        folded = line.casefold()
        if "failed:" in folded or "conclusion=failure" in folded:
            explicit.extend(refs)
    explicit_refs = _unique_refs(explicit, current)
    marker_seen = any(
        marker in line.casefold() for marker in _RELAY_MARKERS for line in lines
    )
    job_ids = tuple(
        dict.fromkeys(
            match.group("job")
            for line in lines
            for match in _FAILED_JOB_ID.finditer(line)
        )
    )
    if explicit_refs:
        return RelaySignal(explicit_refs, (), True)
    if marker_seen and job_ids:
        return RelaySignal((), job_ids, True)
    header_refs = [
        github_run_ref(current.repo, match.group("run"))
        for line in lines
        for match in _RUN_HEADER.finditer(line)
    ]
    candidates = _unique_refs([*header_refs, *all_refs], current)
    if marker_seen:
        return RelaySignal(candidates, (), True)
    if len(candidates) == 1 and terminal_error(log) is None:
        child = candidates[0]
        if run_conclusion is not None and run_conclusion(child) == "failure":
            return RelaySignal((child,), (), True)
        return RelaySignal((), (), False, child_not_failed=True)
    return RelaySignal((), (), False)


def _last_useful_line(log: str) -> str:
    for line in reversed(_clean_lines(log)):
        if line and not any(generic in line.casefold() for generic in _GENERIC_ERRORS):
            return line
    return ""


def _chain_entry(ref: RunRef, job: str = "", job_url: str = "") -> dict[str, str]:
    return {
        "repo": ref.repo,
        "run_id": ref.run_id,
        "url": ref.url,
        "failed_job": job,
        "failed_job_url": job_url,
    }


def _stopped(chain: list[dict[str, str]], reason: str, recovery: str) -> dict[str, Any]:
    return {
        "complete": False,
        "chain": chain,
        "terminal_job": "",
        "terminal_job_url": "",
        "terminal_error": "",
        "stop_reason": reason,
        "recovery": recovery,
    }


def walk_failure_chain(
    origin: RunRef,
    *,
    inspect_run: InspectRun,
    resolve_job: ResolveJob,
    max_hops: int = MAX_TRACE_HOPS,
) -> dict[str, Any]:
    """Walk relays until a failed job supplies its own diagnostic."""
    current = origin
    chain: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _hop in range(max_hops):
        key = (current.repo.casefold(), current.run_id)
        if key in seen:
            return _stopped(
                chain,
                f"failure trace cycled back to {current.url}",
                "inspect the reached run URLs and remove the cyclic dispatch relay",
            )
        seen.add(key)
        chain.append(_chain_entry(current))
        try:
            snapshot = inspect_run(current)
        except Exception as exc:
            return _stopped(
                chain,
                f"could not inspect {current.url}: {exc}",
                "restore Actions read/log permission for this hop, then rerun the trace",
            )
        relay_refs: list[tuple[RunRef, str, str]] = []
        relay_without_target: list[str] = []
        terminal_candidates: list[tuple[tuple[int, int], str, str, str]] = []
        for job in snapshot.failed_jobs:
            try:
                signal = relay_signal(
                    job.log,
                    current,
                    run_conclusion=lambda ref: (
                        "failure" if inspect_run(ref).failed_jobs else "success"
                    ),
                )
            except Exception as exc:
                return _stopped(
                    chain,
                    f"linked run conclusion unreadable: {current.url}: {exc}",
                    "restore Actions read permission for that run, then rerun the trace",
                )
            resolved = list(signal.run_refs)
            for job_id in signal.job_ids:
                try:
                    resolved.append(resolve_job(current.repo, job_id))
                except Exception as exc:
                    relay_without_target.append(f"job {job_id}: {exc}")
            for ref in _unique_refs(resolved, current):
                relay_refs.append((ref, job.name, job.url))
            if signal.observed and not resolved and not signal.job_ids:
                relay_without_target.append(job.log_error or job.name)
            candidate = terminal_candidate(job.log)
            if candidate:
                score, error_text = candidate
                terminal_candidates.append((score, job.name, error_text, job.url))
            elif signal.child_not_failed and (useful := _last_useful_line(job.log)):
                terminal_candidates.append(
                    ((1, len(useful)), job.name, useful, job.url)
                )
        unique_relays = {
            (ref.repo.casefold(), ref.run_id): (ref, job, job_url)
            for ref, job, job_url in relay_refs
        }
        if len(unique_relays) == 1:
            downstream, relay_job, relay_job_url = next(iter(unique_relays.values()))
            chain[-1]["failed_job"] = relay_job
            chain[-1]["failed_job_url"] = relay_job_url
            current = downstream
            continue
        if len(unique_relays) > 1:
            urls = ", ".join(
                sorted(ref.url for ref, _job, _job_url in unique_relays.values())
            )
            return _stopped(
                chain,
                f"relay at {current.url} named multiple failed runs: {urls}",
                "inspect the listed runs and identify the authoritative downstream hop",
            )
        if relay_without_target:
            return _stopped(
                chain,
                f"relay at {current.url} did not resolve its downstream run "
                f"({'; '.join(relay_without_target)})",
                "check the printed hop and its Actions job/run visibility, then rerun",
            )
        if terminal_candidates:
            _score, job_name, error_text, job_url = max(
                terminal_candidates, key=lambda item: item[0]
            )
            chain[-1]["failed_job"] = job_name
            chain[-1]["failed_job_url"] = job_url
            return {
                "complete": True,
                "chain": chain,
                "terminal_job": job_name,
                "terminal_job_url": job_url,
                "terminal_error": error_text,
                "stop_reason": "",
                "recovery": "",
            }
        log_errors = [job.log_error for job in snapshot.failed_jobs if job.log_error]
        detail = "; ".join(log_errors) or "no diagnostic error line was recognized"
        return _stopped(
            chain,
            f"{current.url} failed but its cause could not be read: {detail}",
            "inspect the reached run and extend the failure-log parser for this shape",
        )
    return _stopped(
        chain,
        f"failure trace exceeded the {max_hops}-hop safety limit",
        "inspect the printed chain for an unexpectedly deep dispatch topology",
    )


__all__ = [
    "FailedJob",
    "RunRef",
    "RunSnapshot",
    "github_run_ref",
    "relay_signal",
    "terminal_error",
    "walk_failure_chain",
]
