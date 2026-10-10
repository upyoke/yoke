"""Copy observers and guards remain inside physical admission through cleanup."""

from dataclasses import replace
import sys

import pytest

from yoke_core.domain import migration_fleet_preflight as preflight
from yoke_core.domain import migration_fleet_preflight_extensions as extensions
from yoke_core.domain import migration_fleet_preflight_transfer as transfer
from yoke_core.domain import migration_rehearsal_copy_lock as admission
from yoke_core.domain.postgres_cluster import ClusterSpec


@pytest.fixture
def copy_environment(monkeypatch, tmp_path):
    spec = ClusterSpec(tmp_path / "cluster", "test")
    monkeypatch.setattr(
        admission.machine_config, "yoke_home", lambda: tmp_path / "home"
    )
    monkeypatch.setattr(preflight, "_live_ownership_verdict", lambda *a, **kw: None)
    monkeypatch.setattr(extensions, "source_extensions", lambda *a: ())
    monkeypatch.setattr(extensions, "extension_pins", lambda *a: ())
    monkeypatch.setattr(extensions, "stage_pinned_extensions", lambda *a, **kw: None)
    events = []

    def held():
        with pytest.raises(admission.RehearsalCopyBusy):
            with admission.copy_lock(spec, "migration_rehearsal_tenant"):
                pytest.fail("copy operation escaped physical admission")

    def dump(_spec, _source, path, **kw):
        held()
        events.append("dump")
        path.write_bytes(b"copy")
        kw["resource_guard"]()

    def operation(name):
        def run(*a, **kw):
            held()
            events.append(name)
            if name == "restore":
                kw["resource_guard"]()

        return run

    def converge(*a):
        held()
        events.append("converge")
        return preflight.Verdict("tenant", True, "diagnostic only")

    monkeypatch.setattr(transfer, "dump_database", dump)
    monkeypatch.setattr(transfer, "drop_copy", operation("drop"))
    monkeypatch.setattr(transfer, "create_copy", operation("create"))
    monkeypatch.setattr(transfer, "restore_copy", operation("restore"))
    monkeypatch.setattr(preflight, "_converge_copy", converge)
    plan = preflight.RehearsalPlan(
        (), lambda *a: (), lambda *a: None, resource_guard=held
    )
    return spec, plan, events, held


@pytest.mark.parametrize("failure", [None, "start", "dumped", "restored", "cleanup"])
def test_observer_failure_cleans_owned_resources_before_admission_release(
    monkeypatch, tmp_path, copy_environment, failure
):
    spec, plan, events, held = copy_environment
    dump = tmp_path / "tenant.dump"

    def observer(stage, path):
        held()
        assert path == dump
        events.append(stage)
        if stage == "start":
            path.write_bytes(b"observer scratch")
        if stage == failure:
            raise RuntimeError(f"{stage} observer refused")

    verdict = preflight.rehearse(
        "source",
        database="tenant",
        plan=replace(plan, copy_observer=observer),
        spec=spec,
        work_dir=tmp_path,
        source_environment="prod-db-admin",
    )
    assert verdict.passed is (failure is None)
    assert "cleanup" in events
    assert not dump.exists()
    if failure in (None, "restored", "cleanup"):
        assert events[-1] == "drop"
        assert events.count("drop") == 2
    else:
        assert "create" not in events
    with admission.copy_lock(spec, "migration_rehearsal_tenant"):
        pass


def test_copy_drop_failure_still_unlinks_dump_and_releases_admission(
    monkeypatch, tmp_path, copy_environment
):
    spec, plan, events, held = copy_environment

    def drop(*a):
        held()
        events.append("drop")
        raise RuntimeError("drop refused")

    monkeypatch.setattr(transfer, "drop_copy", drop)
    verdict = preflight.rehearse(
        "source",
        database="tenant",
        plan=plan,
        spec=spec,
        work_dir=tmp_path,
        source_environment="prod-db-admin",
    )
    assert not verdict.passed
    assert events.count("drop") == 2
    assert not (tmp_path / "tenant.dump").exists()
    with admission.copy_lock(spec, "migration_rehearsal_tenant"):
        pass


def test_resource_guard_reaps_transfer_before_admission_release(tmp_path, monkeypatch):
    monkeypatch.setattr(
        admission.machine_config, "yoke_home", lambda: tmp_path / "home"
    )
    spec = ClusterSpec(tmp_path / "cluster", "test")
    processes = []
    original = transfer.subprocess.Popen

    def spawn(*a, **kw):
        process = original(*a, **kw)
        processes.append(process)
        return process

    def refuse():
        raise RuntimeError("resource headroom exhausted")

    monkeypatch.setattr(transfer.subprocess, "Popen", spawn)
    with admission.copy_lock(spec, "copy"):
        with pytest.raises(RuntimeError, match="resource headroom exhausted"):
            transfer.run_transfer(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=10,
                resource_guard=refuse,
            )
        assert processes[0].returncode is not None
        with pytest.raises(admission.RehearsalCopyBusy):
            with admission.copy_lock(spec, "copy"):
                pass
    with admission.copy_lock(spec, "copy"):
        pass
