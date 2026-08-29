"""Trace a failed deployment through relayed GitHub Actions runs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Iterable


MAX_TRACE_HOPS = 8
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TIMESTAMP = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T\S+Z\s+")
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
_GENERIC_ERRORS = (
    "process completed with exit code",
    "hosted train concluded failure",
    "deployment did not complete",
    "promotion did not complete",
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


@dataclass(frozen=True)
class RunSnapshot:
    ref: RunRef
    failed_jobs: tuple[FailedJob, ...]


@dataclass(frozen=True)
class RelaySignal:
    run_refs: tuple[RunRef, ...]
    job_ids: tuple[str, ...]
    observed: bool


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


def _clean_lines(log: str) -> list[str]:
    return [
        _TIMESTAMP.sub("", _ANSI.sub("", raw)).strip()
        for raw in str(log or "").splitlines()
    ]


def _unique_refs(refs: Iterable[RunRef], current: RunRef) -> tuple[RunRef, ...]:
    unique: dict[tuple[str, str], RunRef] = {}
    current_key = (current.repo.casefold(), current.run_id)
    for ref in refs:
        key = (ref.repo.casefold(), ref.run_id)
        if key != current_key:
            unique[key] = ref
    return tuple(unique.values())


def relay_signal(log: str, current: RunRef) -> RelaySignal:
    """Identify a downstream-failure relay without treating it as the cause."""
    lines = _clean_lines(log)
    explicit: list[RunRef] = []
    all_refs: list[RunRef] = []
    for line in lines:
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
        return RelaySignal(candidates, (), True)
    return RelaySignal((), (), False)


def _error_score(text: str) -> tuple[int, int]:
    folded = text.casefold()
    if "unauthorized: authentication required" in folded:
        return 100, len(text)
    if "assertionerror:" in folded:
        return 90, len(text)
    if "error response from daemon:" in folded:
        return 85, len(text)
    if "failed " in folded and " - " in text:
        return 80, len(text)
    if "error:" in folded or "##[error]" in folded:
        return 70, len(text)
    return 0, len(text)


def terminal_error(log: str) -> str | None:
    """Select the most diagnostic non-relay error line from one job log."""
    candidates: list[tuple[tuple[int, int], str]] = []
    for line in _clean_lines(log):
        text = line.split("##[error]", 1)[-1].strip() if "##[error]" in line else line
        folded = text.casefold()
        if not text or any(generic in folded for generic in _GENERIC_ERRORS):
            continue
        score = _error_score(text)
        if score[0]:
            candidates.append((score, text))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _chain_entry(ref: RunRef, job: str = "") -> dict[str, str]:
    return {
        "repo": ref.repo,
        "run_id": ref.run_id,
        "url": ref.url,
        "failed_job": job,
    }


def _stopped(
    chain: list[dict[str, str]],
    reason: str,
    recovery: str,
) -> dict[str, Any]:
    return {
        "complete": False,
        "chain": chain,
        "terminal_job": "",
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
        relay_refs: list[tuple[RunRef, str]] = []
        relay_without_target: list[str] = []
        terminal_candidates: list[tuple[tuple[int, int], str, str]] = []
        for job in snapshot.failed_jobs:
            signal = relay_signal(job.log, current)
            resolved = list(signal.run_refs)
            for job_id in signal.job_ids:
                try:
                    resolved.append(resolve_job(current.repo, job_id))
                except Exception as exc:
                    relay_without_target.append(f"job {job_id}: {exc}")
            for ref in _unique_refs(resolved, current):
                relay_refs.append((ref, job.name))
            if signal.observed and not resolved and not signal.job_ids:
                relay_without_target.append(job.log_error or job.name)
            error_text = terminal_error(job.log)
            if error_text:
                terminal_candidates.append(
                    (_error_score(error_text), job.name, error_text)
                )
        unique_relays = {
            (ref.repo.casefold(), ref.run_id): (ref, job) for ref, job in relay_refs
        }
        if len(unique_relays) == 1:
            downstream, relay_job = next(iter(unique_relays.values()))
            chain[-1]["failed_job"] = relay_job
            current = downstream
            continue
        if len(unique_relays) > 1:
            urls = ", ".join(sorted(ref.url for ref, _job in unique_relays.values()))
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
            _score, job_name, error_text = max(
                terminal_candidates, key=lambda item: item[0]
            )
            chain[-1]["failed_job"] = job_name
            return {
                "complete": True,
                "chain": chain,
                "terminal_job": job_name,
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
