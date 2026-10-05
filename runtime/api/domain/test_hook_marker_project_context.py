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
