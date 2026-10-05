"""Missing project context cannot borrow the serving process's checkout."""

from contextlib import nullcontext

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts import project_defaults
from yoke_core.domain import project_selection
from yoke_core.domain.project_identity import resolve_project


def test_unmapped_directory_has_no_default(monkeypatch, tmp_path):
    monkeypatch.setattr(project_defaults, "project_id", lambda _path: None)
    assert project_defaults.default_project_for_directory(tmp_path) is None
    monkeypatch.setattr(project_defaults, "project_id", lambda _path: 42)
    assert project_defaults.default_project_for_directory(tmp_path) == "42"


@pytest.mark.parametrize("project", [None, "", "  "])
def test_local_missing_project_lists_only_connected_roster(
    monkeypatch, tmp_path, project
):
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda _p: None
    )
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay",
        lambda _function, _payload: {"rows": [{"slug": "accessible"}]},
    )
    with pytest.raises(project_defaults.MissingProjectError) as error:
        project_selection.required_local_project(tmp_path, project)
    assert "project_required: no project given — pass --project P" in str(error.value)
    assert "Accessible projects: accessible" in str(error.value)


def test_explicit_environment_and_checkout_selection(monkeypatch, tmp_path):
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda _p: "42"
    )
    assert (
        project_selection.required_local_project(tmp_path, "explicit", env={})
        == "explicit"
    )
    assert (
        project_selection.required_local_project(tmp_path, env={"YOKE_PROJECT": "env"})
        == "env"
    )
    assert project_selection.required_local_project(tmp_path, env={}) == "42"


def test_server_resolution_never_reads_checkout(test_db, monkeypatch):
    def forbidden(_path):
        raise AssertionError("server checkout is not caller authority")

    monkeypatch.setattr(project_defaults, "project_id", forbidden)
    with pytest.raises(project_defaults.MissingProjectError, match="project_required"):
        resolve_project(test_db, None)
    assert resolve_project(test_db, None, required=False) is None


def test_server_refusal_filters_project_names(test_db):
    rows = test_db.execute("SELECT id, slug FROM projects ORDER BY id").fetchall()
    assert project_selection.missing_project_on_connection(
        test_db,
        visible_project_ids=set(),
    ).endswith("Accessible projects: none.")
    if rows:
        selected = rows[0]
        message = project_selection.missing_project_on_connection(
            test_db,
            visible_project_ids={selected[0]},
        )
        assert message.endswith(f"Accessible projects: {selected[1]}.")


def test_create_handler_refuses_before_instruction_or_write(test_db, monkeypatch):
    from yoke_core.domain.handlers.items_create import handle_item_create

    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda: nullcontext(test_db)
    )
    monkeypatch.setattr(
        "yoke_core.domain.backlog_create_op.execute_create",
        lambda **_kwargs: pytest.fail("missing project must never write"),
    )
    request = FunctionCallRequest(
        function="items.create",
        actor=ActorContext(session_id="missing-project-test"),
        target=TargetRef(kind="global"),
        payload={"title": "test", "workflow": "dash"},
        options={"visible_project_ids": []},
    )
    result = handle_item_create(request)
    assert result.primary_success is False
    assert result.error.code == "project_required"
    assert result.error.message.endswith("Accessible projects: none.")


def test_project_scoped_tools_refuse_without_binding(monkeypatch, tmp_path):
    from yoke_core.domain.qa_environment_declaration import load_declaration
    from yoke_core.engines.doctor_context import default_project
    from yoke_core.tools.pytest_remote_selection import resolve_route, Refusal

    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda _p: None
    )
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay",
        lambda _function, _payload: {"rows": []},
    )
    with pytest.raises(project_defaults.MissingProjectError):
        load_declaration(checkout=tmp_path)
    with pytest.raises(project_defaults.MissingProjectError):
        default_project(tmp_path)
    result = resolve_route(tmp_path, pytest_args=[], impacted_base=None, env={})
    assert isinstance(result, Refusal)
    assert "project_required" in result.message


def test_unmapped_tooling_does_not_read_another_projects_declarations(
    monkeypatch, tmp_path
):
    from yoke_core.tools import impacted_project_test_roots as roots
    from yoke_core.engines import lane_residue_declared_paths as residue

    monkeypatch.setattr(roots, "default_project_for_directory", lambda _p: None)
    monkeypatch.setattr(residue, "default_project_for_directory", lambda _p: None)
    monkeypatch.setattr(
        roots, "_try_read", lambda _p: pytest.fail("unmapped project read")
    )
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == ()
    assert residue.declared_disposable_roots(tmp_path) == frozenset()
