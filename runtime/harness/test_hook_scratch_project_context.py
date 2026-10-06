"""Explicit hook project binding covers every lifecycle scratch owner."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from yoke_core.domain import session_orientation_delivery as orientation
from yoke_core.hooks import codex_payload, helpers_markers
from yoke_core.hooks.session_dispatch_first_prompt import first_prompt


def test_all_lifecycle_marker_owners_use_bound_project(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    monkeypatch.setenv("YOKE_PROJECT", "9")
    with scratch.scratch_project("7"):
        codex_payload.write_runtime_cache("session", '{"source":"startup"}')
        assert codex_payload.read_runtime_cache_field("session", "source") == "startup"
        assert codex_payload.session_marker_path("session").startswith(
            str(tmp_path / "7")
        )
        assert first_prompt("session", codex=True)
        assert first_prompt("session", codex=False)
        helpers_markers.write_current_item_marker(42)
        helpers_markers.write_done_item_marker(42)
        assert helpers_markers.read_current_item_marker() == "42"
        assert helpers_markers.read_done_item_marker() == "42"
        monkeypatch.setattr(orientation, "_composed_session", None)
        assert not orientation.record_orientation_attempt("session")
        orientation.confirm_orientation_delivery()
        assert orientation.orientation_delivered("session")
    assert not (tmp_path / "9").exists()
    assert scratch.resolve_active_project() == "9"


def test_concurrent_project_bindings_do_not_leak_on_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    monkeypatch.setenv("YOKE_PROJECT", "3")
    barrier = Barrier(2)

    def run(project):
        with pytest.raises(RuntimeError), scratch.scratch_project(project):
            barrier.wait(timeout=5)
            assert scratch.hook_marker_path("marker").parent == (
                tmp_path / project / "hook-markers"
            )
            raise RuntimeError("evaluation aborted")
        return scratch.resolve_active_project()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, ["1", "2"])) == ["3"] * 2


def test_missing_bound_project_is_not_swallowed():
    from yoke_contracts.project_defaults import MissingProjectError

    with pytest.raises(MissingProjectError, match="project_required"):
        with scratch.scratch_project(""):
            pytest.fail("missing project must refuse")
