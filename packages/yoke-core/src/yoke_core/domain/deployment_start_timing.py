"""Flushed deployment-start diagnostics, carried with responses on HTTPS."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
from time import monotonic

PREFIX = "Deployment start timing: "
_SCOPE = ContextVar("deployment_start_timing", default=None)


def _transport():
    from yoke_core.domain.events_transport_guard import _active_transport_is_https

    return "https" if _active_transport_is_https() else "local-postgres"


@contextmanager
def timing_scope(run_id, *, collect=False, capture=None):
    records = []
    state = {
        "run_id": run_id,
        "source_sha": "",
        "member_count": None,
        "transport": _transport(),
        "records": records,
        "collect": collect,
        "capture": capture,
    }
    token = _SCOPE.set(state)
    try:
        yield records
    finally:
        _SCOPE.reset(token)


def timing_facts(*, source_sha=None, member_count=None):
    state = _SCOPE.get()
    if state is not None:
        if source_sha is not None:
            state["source_sha"] = source_sha
        if member_count is not None:
            state["member_count"] = member_count


def emit_records(records):
    for record in records or ():
        print(PREFIX + json.dumps(record, sort_keys=True), flush=True)


def _emit(step, phase, elapsed_ms=None, outcome=None):
    state = _SCOPE.get()
    if state is None:
        return
    record = {
        key: state[key] for key in ("run_id", "source_sha", "member_count", "transport")
    }
    record.update(
        step=step, phase=phase, timestamp=datetime.now(timezone.utc).isoformat()
    )
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
            print(line, flush=True)


@contextmanager
def start_step(step):
    started = monotonic()
    _emit(step, "start")
    outcome = "ok"
    try:
        yield
    except BaseException:
        outcome = "failed"
        raise
    finally:
        _emit(step, "end", round((monotonic() - started) * 1000, 3), outcome)


def timed_call(step, function, *args, **kwargs):
    with start_step(step):
        return function(*args, **kwargs)


def timed_pipeline(function):
    @wraps(function)
    def run(primary_arg, *args, **kwargs):
        run_id = primary_arg
        with timing_scope(run_id):
            from yoke_core.domain.deploy_pipeline_pinned_source import (
                PINNED_RELEASE_ENV,
            )

            timing_facts(source_sha=os.environ.get(PINNED_RELEASE_ENV, ""))
            return function(run_id, *args, **kwargs)

    return run


def timed_handler(function):
    """Return server substeps so the driver can flush them into its capture."""

    @wraps(function)
    def run(request):
        run_id = str(request.target.workflow_run_id or "")
        with timing_scope(run_id, collect=True) as records:
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

    with timing_scope(run_id):
        timing_facts(source_sha=env.get(PINNED_RELEASE_ENV, ""))
        _emit(
            "child_start",
            "end",
            round((monotonic() - float(started)) * 1000, 3),
            outcome,
        )
