"""Item claims use authority identity and only the caller machine's folders."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from yoke_cli.commands.adapters import claims
from yoke_cli.commands.adapters import claims_work_folder_guard as guard
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


@pytest.fixture
def item(monkeypatch):
    value = {"project_id": 4, "public_ref": "GAR-3", "title": "Plant trees"}
    monkeypatch.setattr(guard, "_work_item", lambda ref: value)
    monkeypatch.setattr(guard, "resolve_project_slug", lambda ref: "garden")
    monkeypatch.setattr(
        guard,
        "load_config",
        lambda: {"projects": [{"project_id": 4, "checkout": "/local/garden"}]},
    )
    return value


@pytest.mark.parametrize(
    "target", [["--item", "GAR-3"], ["--epic", "GAR-3", "--task-num", "2"]]
)
def test_moved_away_refused_before_dispatch(item, monkeypatch, capsys, target):
    monkeypatch.setattr(guard, "default_project_for_directory", lambda path: "9")

    def forbidden(**kw):
        pytest.fail("claim dispatch must not happen")

    monkeypatch.setattr(claims, "dispatch_and_emit", forbidden)
    assert claims.claims_work_acquire(target) == 1
    err = capsys.readouterr().err
    assert "CLAIM_FOLDER_MISMATCH" in err
    assert "/local/garden" in err and "GAR-3 (Plant trees)" in err


def test_lane_worktree_maps_to_parent_project(tmp_path, monkeypatch, item):
    from yoke_contracts.machine_config import paths

    checkout = tmp_path / "garden"
    lane = checkout / ".worktrees" / "worker"
    lane.mkdir(parents=True)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"projects": [{"project_id": 4, "checkout": str(checkout)}]})
    )
    monkeypatch.delenv(paths.HOME_ENV, raising=False)
    monkeypatch.setenv(paths.CONFIG_FILE_ENV, str(config))
    monkeypatch.chdir(lane)
    assert guard.default_project_for_directory(Path.cwd()) == "4"
    assert guard.check_caller_folder("GAR-3") is None


def test_unmapped_project_names_registration(item, monkeypatch):
    monkeypatch.setattr(guard, "load_config", lambda: {"projects": []})
    line = guard.render_folder_line(4, "garden", "GAR-3", "Plant trees")
    assert "No local checkout" in line
    assert "yoke project register CHECKOUT --project-id 4" in line
    assert "/local/garden" not in line


@pytest.mark.parametrize(
    "code", ["SESSION_MACHINE_SCOPE_WORK_REFUSED", "SESSION_PROJECT_MISMATCH"]
)
def test_server_mismatch_code_rendered_with_local_folder(item, code):
    response = FunctionCallResponse(
        success=False,
        function="claims.work.acquire",
        version="v1",
        request_id="test",
        error=FunctionError(code=code, message="immutable session mismatch"),
    )
    recovered = guard.folder_response_recovery("GAR-3")(response, None)
    assert recovered.error.code == code
    assert "/local/garden" in recovered.error.message
    assert "GAR-3 (Plant trees)" in recovered.error.message


def test_matching_folder_dispatches(item, monkeypatch):
    monkeypatch.setattr(guard, "default_project_for_directory", lambda path: "4")
    called = []
    monkeypatch.setattr(
        claims, "dispatch_and_emit", lambda **kw: called.append(kw) or 0
    )
    assert claims.claims_work_acquire(["--item", "GAR-3"]) == 0
    assert called[0]["function_id"] == "claims.work.acquire"


def test_process_claim_exempt(monkeypatch):
    monkeypatch.setattr(claims, "required_project_context", lambda project: "4")
    monkeypatch.setattr(
        claims, "refuse_caller_folder", lambda ref: pytest.fail("item guard called")
    )
    monkeypatch.setattr(claims, "dispatch_and_emit", lambda **kw: 0)
    assert claims.claims_work_acquire(["--process", "DOCTOR"]) == 0


def test_unreachable_item_lookup_refuses(monkeypatch, capsys):
    monkeypatch.setattr(guard, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(guard, "build_actor", lambda: None)
    monkeypatch.setattr(guard, "item_target", lambda *a: None)
    monkeypatch.setattr(
        guard,
        "call_dispatcher",
        lambda **kw: SimpleNamespace(
            success=False,
            error=SimpleNamespace(
                code="relay_unavailable", message="Reconnect authority"
            ),
        ),
    )
    assert guard.refuse_caller_folder("GAR-3")
    assert "relay_unavailable: Reconnect authority" in capsys.readouterr().err


def test_items_get_uses_served_projection(monkeypatch):
    calls = []
    monkeypatch.setattr(guard, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(guard, "build_actor", lambda: None)

    def dispatch(**kw):
        calls.append(kw)
        return SimpleNamespace(
            success=True,
            result={
                "public_ref": "GAR-3",
                "fields": {"project_id": 4, "title": "Plant trees"},
            },
        )

    monkeypatch.setattr(guard, "call_dispatcher", dispatch)
    assert guard._work_item("GAR-3")["project_id"] == 4
    assert calls[0]["function_id"] == "items.get.run"
    assert calls[0]["payload"]["fields"] == ["project_id", "title"]
