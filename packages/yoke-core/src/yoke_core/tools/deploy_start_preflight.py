"""Capture the deploy watcher's preflight before the child exists."""

from yoke_core.domain.deployment_start_timing import timing_scope, timed_call


def prepare_driver(run_id, raw_path, prepare):
    raw_path.write_text("", encoding="utf-8")
    with timing_scope(run_id, capture=raw_path):
        return timed_call("driver_preflight", prepare, run_id)


def launch_watched_child(kind, raw_stream, launch, *args, **kwargs):
    from yoke_core.tools._watch_designed_waits import DEPLOY_WATCH_KIND

    if kind != DEPLOY_WATCH_KIND:
        return launch(*args, **kwargs)
    from yoke_core.domain.deployment_start_timing import start_step

    argv = args[0] if args else []
    run_id = next((str(value) for value in argv if str(value).startswith("run-")), "")
    with timing_scope(run_id, capture=raw_stream), start_step("child_start"):
        return launch(*args, **kwargs)
