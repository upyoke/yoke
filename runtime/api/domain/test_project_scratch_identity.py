"""Project id, slug, environment, and hook context share scratch namespaces."""

import pytest

from yoke_contracts.project_defaults import MissingProjectError
from yoke_core.domain import project_scratch_dir as scratch
from yoke_core.domain import project_scratch_identity as identity
from yoke_core.domain import project_selection


@pytest.fixture
def lookup(monkeypatch):
    calls = []
    monkeypatch.setattr(identity, "_control_plane_selected", lambda: True)
    monkeypatch.setattr(identity, "local_connection_or_none", lambda connect: None)

    def relay(function, payload):
        calls.append((function, payload))
        if function == "projects.list":
            return {"rows": [{"id": 7, "slug": "renamed"}]}
        assert function == "projects.get"
        assert payload == {"project": "renamed", "field": "id"}
        return {"value": 7}

    monkeypatch.setattr(identity, "relay", relay)
    monkeypatch.setattr("yoke_core.domain.control_plane_transport.relay", relay)
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda p: "7"
    )
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    return calls


@pytest.mark.parametrize("reference", ["7", "007", "renamed", None])
def test_inputs_share_hook_and_cache_paths(lookup, monkeypatch, tmp_path, reference):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    explicit = scratch.hook_marker_path("done", project=reference)
    monkeypatch.setenv("YOKE_PROJECT", "renamed")
    environmental = scratch.hook_marker_path("done")
    with scratch.scratch_project("renamed"):
        bound = scratch.hook_marker_path("done")
    assert (
        explicit == environmental == bound == tmp_path / "7" / "hook-markers" / "done"
    )
    assert scratch.harness_runtime_cache_path("cache") == (
        tmp_path / "7" / "harness-runtime-cache" / "cache"
    )


def test_context_binding_preserves_explicit_override_and_restores(lookup, monkeypatch):
    monkeypatch.setenv("YOKE_PROJECT", "8")
    with scratch.scratch_project("renamed"):
        assert scratch.resolve_active_project() == "7"
        assert scratch.resolve_active_project("9") == "9"
    assert scratch.resolve_active_project() == "8"


def test_numeric_namespace_needs_no_control_plane(lookup):
    assert identity.resolve_project_namespace("007") == "7"
    assert lookup == []


def test_local_lookup_uses_database_identity(monkeypatch, test_db):
    monkeypatch.setattr(identity, "local_connection_or_none", lambda connect: test_db)
    assert identity.resolve_project_namespace("yoke") == "1"


def test_unmapped_directory_keeps_project_refusal(lookup, monkeypatch):
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda p: None
    )
    with pytest.raises(MissingProjectError, match="pass --project"):
        scratch.resolve_active_project()


def test_unresolved_slug_never_becomes_a_path(lookup, monkeypatch):
    monkeypatch.setattr(identity, "relay", lambda *args: {"value": None})
    with pytest.raises(LookupError, match="accessible numeric project id"):
        scratch.resolve_active_project("unknown")


@pytest.mark.parametrize("connected", [True, False])
def test_artifact_writer_and_reader_share_namespace(
    lookup, monkeypatch, tmp_path, connected
):
    from yoke_core.domain import qa_artifacts

    monkeypatch.setattr(identity, "_control_plane_selected", lambda: connected)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    artifact = qa_artifacts.artifact_file_path("renamed", 12, 34, "output.log")
    artifact.write_text("evidence")
    assert artifact.relative_to(tmp_path).parts[0] == ("7" if connected else "renamed")
    assert qa_artifacts.is_sanctioned_artifact_path(artifact, "renamed", 12, 34)
    assert not qa_artifacts.is_sanctioned_artifact_path(artifact, "renamed", 12, 35)
    if connected:
        assert qa_artifacts.is_sanctioned_artifact_path(artifact, "7", 12, 34)
    else:
        assert lookup == []


def test_selected_but_unreachable_plane_keeps_namespace_refusal(lookup, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("control plane unavailable")

    monkeypatch.setattr(identity, "relay", unavailable)
    with pytest.raises(RuntimeError, match="control plane unavailable"):
        scratch.resolve_active_project("renamed")
