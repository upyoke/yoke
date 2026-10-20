"""Flushed deployment-start diagnostics, carried with responses on HTTPS.

A driver-side scope opened with ``persist=True`` also stores its run's
start/end records through ``deployment_runs.timings.record`` at each pipeline
stage and when it closes, so ``yoke deployment-runs timings RUN-ID`` answers
from any machine.
"""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import partial, wraps
import json
import os
import sys
from pathlib import Path
from time import monotonic
from threading import Event, Thread
from uuid import uuid4

from yoke_contracts.timestamps import iso8601_now

PREFIX = "Deployment start timing: "
_SCOPE = ContextVar("deployment_start_timing", default=None)
RECORD_FUNCTION_ID = "deployment_runs.timings.record"
REFUSAL_PREFIX = "Deployment timing record refused: "


def _transport():
    from yoke_core.domain.events_transport_guard import _active_transport_is_https

    return "https" if _active_transport_is_https() else "local-postgres"


@contextmanager
def timing_scope(run_id, *, collect=False, capture=None, persist=False):
    records = []
    state = {
        "run_id": run_id,
        "source_sha": "",
        "member_count": None,
        "transport": _transport(),
        "records": records,
        "collect": collect,
        "capture": capture,
        "persist": persist,
        "batch_id": uuid4().hex,
        "sent": 0,
    }
    token = _SCOPE.set(state)
    try:
        yield records
    finally:
        _SCOPE.reset(token)
        _persist(state)


def flush_timings():
    """Store the open scope's unsent records now; the pipeline calls this per stage."""
    state = _SCOPE.get()
    if state is not None:
        _persist(state)


def _persist(state):
    """Send unsent start/end records; a refusal is reported, never raised.

    Timings are diagnostics: the deployment's outcome must not depend on
    whether its measurements could be written. Each record keeps its scope
    batch and sequence, so a later flush retries a refused batch without
    duplicating one that landed.
    """
    run_id = state["run_id"]
    if not state["persist"] or not run_id:
        return
    from yoke_core.domain.deployment_run_timings import (
        MAX_BATCH_RECORDS,
        persistable,
    )

    stored = [r for r in persistable(state["records"]) if r.get("run_id") == run_id]
    while state["sent"] < len(stored):
        first = state["sent"]
        batch = stored[first : first + MAX_BATCH_RECORDS]
        reason = _record_batch(run_id, state["batch_id"], first, batch)
        if reason:
            print(
                f"{REFUSAL_PREFIX}run {run_id}: {reason}. The run is unaffected; "
                "its `Deployment start timing:` lines remain in this capture and "
                "the next stage retries them. "
                f"Recovery: confirm `yoke deployment-runs timings {run_id}` is "
                "served (`yoke env list` names the control plane), then attach "
                "this capture to the evidence that needed the timings.",
                file=sys.stderr,
                flush=True,
            )
            return
        state["sent"] += len(batch)


def _record_batch(run_id, batch_id, first_sequence, batch):
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    try:
        response = call_dispatcher(
            function_id=RECORD_FUNCTION_ID,
            target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
            payload={
                "batch_id": batch_id,
                "first_sequence": first_sequence,
                "records": batch,
            },
        )
    except Exception as exc:  # diagnostics never change the run's outcome
        return f"{type(exc).__name__}: {exc}"
    if response.success:
        return ""
    error = response.error
    if error is None:
        return "request failed without a named error"
    hint = f" ({error.recovery_hint})" if error.recovery_hint else ""
    return f"{error.code}: {error.message}{hint}"


def timing_facts(*, run_id=None, source_sha=None, member_count=None):
    state = _SCOPE.get()
    if state is not None:
        if run_id is not None:
            state["run_id"] = run_id
        if source_sha is not None:
            state["source_sha"] = source_sha
        if member_count is not None:
            state["member_count"] = member_count


def emit_records(records, *, stream=None):
    """Flush server-returned records; the open driver scope also keeps them."""
    state = _SCOPE.get()
    for record in records or ():
        print(PREFIX + json.dumps(record, sort_keys=True), file=stream, flush=True)
        if state is not None and not state["collect"]:
            state["records"].append(record)


def _emit(step, phase, elapsed_ms=None, outcome=None, *, stream=None, **facts):
    state = _SCOPE.get()
    if state is None:
        return
    record = {
        key: state[key] for key in ("run_id", "source_sha", "member_count", "transport")
    }
    record.update(step=step, phase=phase, timestamp=iso8601_now(), **facts)
    if elapsed_ms is not None:
        record.update(elapsed_ms=elapsed_ms, outcome=outcome)
    state["records"].append(record)
    if not state["collect"]:
        line = PREFIX + json.dumps(record, sort_keys=True)
        if hasattr(state["capture"], "write"):
            print(line, file=state["capture"], flush=True)
        elif state["capture"] is not None:
            with Path(state["capture"]).open("a", encoding="utf-8") as stream:
                print(line, file=stream, flush=True)
        else:
            print(line, file=stream, flush=True)


@contextmanager
def start_step(step, *, heartbeat=False, record_count=None):
    started = monotonic()
    progress = (
        {}
        if record_count is None
        else {"record_count": record_count, "completed_count": 0}
    )
    _emit(step, "start", **progress)
    stopped = Event()
    pulse = None
    if heartbeat and _SCOPE.get() is not None:
        # The pulse thread writes to the step's own stream: a redirect the step
        # body installs later (a replay proof capturing its entry's output) is
        # process-wide and must not swallow or be polluted by these lines.
        step_stream = sys.stdout

        def report_running():
            while not stopped.wait(30):
                _emit(
                    step,
                    "running",
                    round((monotonic() - started) * 1000, 3),
                    "pending",
                    stream=step_stream,
                    **progress,
                )

        pulse = Thread(target=copy_context().run, args=(report_running,), daemon=True)
        pulse.start()
    outcome = "ok"
    try:
        yield progress
    except BaseException as exc:
        outcome = "failed"
        progress["reason_code"] = str(getattr(exc, "code", "") or type(exc).__name__)
        raise
    finally:
        stopped.set()
        if pulse is not None:
            pulse.join()
        _emit(
            step, "end", round((monotonic() - started) * 1000, 3), outcome, **progress
        )


def timed_call(step, function, *args, **kwargs):
    with start_step(step):
        return function(*args, **kwargs)


def timed_pipeline(function):
    @wraps(function)
    def run(primary_arg, *args, **kwargs):
        run_id = primary_arg
        with timing_scope(run_id, persist=True):
            from yoke_core.domain.deploy_pipeline_pinned_source import (
                PINNED_RELEASE_ENV,
            )

            timing_facts(source_sha=os.environ.get(PINNED_RELEASE_ENV, ""))
            return function(run_id, *args, **kwargs)

    return run


def timed_handler(function=None, *, progress=False):
    """Return server substeps so the driver can flush them into its capture."""
    if function is None:
        return partial(timed_handler, progress=progress)

    @wraps(function)
    def run(request):
        run_id = str(request.target.workflow_run_id or "")
        with timing_scope(run_id, collect=not progress, capture=sys.stderr) as records:
            outcome = function(request)
        outcome.result_payload["start_timings"] = records
        return outcome

    return run


_REEXEC_START_ENV = "YOKE_DEPLOY_CHILD_START"


def begin_reexec(env):
    """Pass the monotonic launch instant across exec without persistent state."""
    env[_REEXEC_START_ENV] = str(monotonic())
    _emit("child_start", "start")


def finish_reexec(run_id, *, outcome="ok", environment=None):
    env = os.environ if environment is None else environment
    started = env.pop(_REEXEC_START_ENV, "")
    if not started:
        return
    from yoke_core.domain.deploy_pipeline_pinned_source import PINNED_RELEASE_ENV

    with timing_scope(run_id, persist=True):
        timing_facts(source_sha=env.get(PINNED_RELEASE_ENV, ""))
        _emit(
            "child_start",
            "end",
            round((monotonic() - float(started)) * 1000, 3),
            outcome,
        )


def timed_preparation(step, function, *args, **kwargs):
    """Report the current database-preparation phase while it is still running."""
    with start_step(step, heartbeat=True):
        return function(*args, **kwargs)


def current_run_id():
    state = _SCOPE.get()
    return state["run_id"] if state else ""
