"""Hook helpers import without a project and refuse scoped writes on demand."""

import importlib

import pytest

from yoke_contracts.project_defaults import MissingProjectError
from yoke_core.domain import project_scratch_dir
from yoke_core.hooks import helpers_markers


def test_import_does_not_resolve_project_paths(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("import attempted project-scoped resolution")

    monkeypatch.setattr(project_scratch_dir, "hook_marker_path", refuse)
    try:
        importlib.reload(helpers_markers)
    finally:
        monkeypatch.undo()
        importlib.reload(helpers_markers)


def test_unattributed_reads_are_empty_and_writes_refuse(monkeypatch):
    def refuse(*args, **kwargs):
        raise MissingProjectError("project_required: caller project missing")

    monkeypatch.setattr(helpers_markers, "hook_marker_path", refuse)
    assert helpers_markers.read_current_item_marker() == ""
    assert helpers_markers.read_done_item_marker() == ""
    with pytest.raises(MissingProjectError, match="project_required"):
        helpers_markers.write_current_item_marker(42)
    with pytest.raises(MissingProjectError, match="project_required"):
        helpers_markers.write_done_item_marker(42)


def test_unattributed_runtime_cache_read_is_empty(monkeypatch):
    from yoke_core.hooks import codex_payload

    def refuse(*args, **kwargs):
        raise MissingProjectError("project_required: caller project missing")

    monkeypatch.setattr(codex_payload, "runtime_cache_path", refuse)
    assert codex_payload.read_runtime_cache_field("session", "source") == ""


def test_unattributed_planning_scratch_has_no_allowed_roots(monkeypatch):
    from yoke_core.domain import path_claim_bash_parser_planning_phase as planning

    def refuse(*args, **kwargs):
        raise MissingProjectError("project_required: caller project missing")

    monkeypatch.setattr(project_scratch_dir, "dispatch_inputs_dir", refuse)
    assert planning.planning_scratch_roots() == ()
