"""Reading a project's declared disposable generated paths for lane cleanup.

``declared_disposable_roots_for_project`` always relays through
``projects.capability_settings.get`` (never a direct DB connection), so
these tests monkeypatch that one call and assert the fail-closed behavior:
an unreachable control plane, a failed response, or an invalid stored
declaration all read as no additional declarations.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

from yoke_contracts.api.function_call import FunctionCallResponse

from yoke_core.engines import lane_residue_declared_paths as module


def _stub_response(
    settings: dict | None, *, success: bool = True
) -> FunctionCallResponse:
    result = {} if settings is None else {"settings_json": json.dumps(settings)}
    return FunctionCallResponse(
        success=success,
        function="projects.capability_settings.get",
        version="v1",
        result=result,
    )


def _patch_dispatcher(monkeypatch, fn):
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", fn
    )


def test_declared_paths_returned_when_present(monkeypatch):
    _patch_dispatcher(
        monkeypatch,
        lambda **_kw: _stub_response(
            {"disposable_generated_paths": ["docs/atlas.md", ".yoke/strategy"]}
        ),
    )

    roots = module.declared_disposable_roots_for_project("yoke")

    assert roots == frozenset(
        {PurePosixPath("docs/atlas.md"), PurePosixPath(".yoke/strategy")}
    )


def test_no_declaration_key_returns_empty(monkeypatch):
    _patch_dispatcher(monkeypatch, lambda **_kw: _stub_response({"wip_cap": 5}))

    assert module.declared_disposable_roots_for_project("yoke") == frozenset()


def test_unreachable_authority_fails_closed(monkeypatch):
    def _raise(**_kw):
        raise RuntimeError("no control plane")

    _patch_dispatcher(monkeypatch, _raise)

    assert module.declared_disposable_roots_for_project("yoke") == frozenset()


def test_failed_response_fails_closed(monkeypatch):
    _patch_dispatcher(monkeypatch, lambda **_kw: _stub_response({}, success=False))

    assert module.declared_disposable_roots_for_project("yoke") == frozenset()


def test_invalid_stored_declaration_fails_closed(monkeypatch):
    _patch_dispatcher(
        monkeypatch,
        lambda **_kw: _stub_response({"disposable_generated_paths": ["../outside"]}),
    )

    assert module.declared_disposable_roots_for_project("yoke") == frozenset()


def test_unreadable_settings_json_fails_closed(monkeypatch):
    _patch_dispatcher(
        monkeypatch,
        lambda **_kw: FunctionCallResponse(
            success=True,
            function="projects.capability_settings.get",
            version="v1",
            result={"settings_json": "not json"},
        ),
    )

    assert module.declared_disposable_roots_for_project("yoke") == frozenset()


def test_none_project_falls_back_to_default_slug(monkeypatch):
    seen = {}

    def _capture(**kwargs):
        seen["project"] = kwargs["payload"]["project"]
        return _stub_response({})

    _patch_dispatcher(monkeypatch, _capture)

    module.declared_disposable_roots_for_project(None)

    assert seen["project"] == module.DEFAULT_PROJECT_SLUG
