"""Registry-dispatched handlers select the tests that call their function ids."""

from __future__ import annotations

from dataclasses import replace

from yoke_core.tools import _impacted_dispatch_edges as dispatch_edges
from yoke_core.tools import _impacted_implicit_edges as implicit_edges
from yoke_core.tools.impacted_tests import FALLBACK_RULES, build_import_index, select
from runtime.api.tools.test_impacted_tests import _tiny_repo, _write

_HUB = "runtime.api.handlers.hub"
_FUNCTION_IDS = {
    "runtime.api.handlers.widgets": frozenset({"widgets.item.create"}),
    "runtime.api.handlers.gadgets": frozenset({"gadgets.item.create"}),
}


def _caller(function_id: str) -> str:
    # Callers reach handlers by naming the id, never by importing them.
    return (
        f"import subprocess\n\ndef test_it():\n    subprocess.run([{function_id!r}])\n"
    )


def _dispatch_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(implicit_edges, "DISPATCH_HUB_MODULE", _HUB)
    root = _tiny_repo(tmp_path)
    _write(root, "runtime/api/handlers/__init__.py", "")
    _write(root, "runtime/api/widget_rules.py", "LIMIT = 1\n")
    _write(
        root,
        "runtime/api/handlers/widgets.py",
        "from runtime.api.widget_rules import LIMIT\n",
    )
    # The hub registers every handler, and a dispatching handler imports
    # the dispatcher that imports the hub.
    _write(
        root,
        "runtime/api/handlers/hub.py",
        "from runtime.api.handlers import widgets, gadgets\n",
    )
    _write(root, "runtime/api/dispatcher.py", "from runtime.api.handlers import hub\n")
    _write(
        root, "runtime/api/handlers/gadgets.py", "from runtime.api import dispatcher\n"
    )
    _write(root, "runtime/api/test_widget_caller.py", _caller("widgets.item.create"))
    _write(root, "runtime/api/test_gadget_caller.py", _caller("gadgets.item.create"))
    _write(root, "runtime/api/widget_adapter.py", "FUNCTION = 'widgets.item.create'\n")
    _write(
        root,
        "runtime/api/test_widget_adapter.py",
        "from runtime.api import widget_adapter\n",
    )
    return replace(
        build_import_index(root),
        dispatch=dispatch_edges.DispatchMap(function_ids=_FUNCTION_IDS),
    )


def test_handler_dependency_change_selects_function_id_callers(tmp_path, monkeypatch):
    index = _dispatch_repo(tmp_path, monkeypatch)

    selection = select(["runtime/api/widget_rules.py"], index, bounded=True)

    assert "runtime/api/test_widget_caller.py" in selection.files
    # A non-test caller naming the id carries its own importing tests.
    assert "runtime/api/test_widget_adapter.py" in selection.files
    # The registration hub imports every handler; crossing it would make
    # every dispatching handler look reached.
    assert "runtime/api/test_gadget_caller.py" not in selection.files


def test_changed_handler_selects_function_id_callers(tmp_path, monkeypatch):
    index = _dispatch_repo(tmp_path, monkeypatch)

    selection = select(["runtime/api/handlers/widgets.py"], index)

    assert "runtime/api/test_widget_caller.py" in selection.files


def test_tree_without_the_registration_hub_has_no_dispatch_edges():
    loaded = dispatch_edges.load_dispatch_map(["runtime.api.leaf"])

    assert loaded == dispatch_edges.DispatchMap()


def test_live_registry_maps_handler_modules_to_their_function_ids():
    loaded = dispatch_edges.load_dispatch_map([dispatch_edges.DISPATCH_HUB_MODULE])

    assert loaded.error == ""
    assert (
        "deployment_runs.create"
        in loaded.function_ids["yoke_core.domain.handlers.deployment_runs"]
    )


def test_unloadable_registry_widens_with_a_named_reason(tmp_path, monkeypatch):
    from yoke_core.domain.handlers import __init_register__ as hub

    def broken():
        raise ImportError("no module named widgets")

    monkeypatch.setattr(hub, "register_all_handlers", broken)
    loaded = dispatch_edges.load_dispatch_map([dispatch_edges.DISPATCH_HUB_MODULE])
    index = replace(build_import_index(_tiny_repo(tmp_path)), dispatch=loaded)

    selection = select(["runtime/api/leaf.py"], index)
    bounded = select(["runtime/api/leaf.py"], index, bounded=True)

    assert "no module named widgets" in loaded.error
    assert f"yoke dev import-check {dispatch_edges.DISPATCH_HUB_MODULE}" in loaded.error
    assert selection.full_sweep is True
    assert selection.fallback_rule == "dispatch_registry_unloadable"
    assert selection.fallback_rule in FALLBACK_RULES
    assert bounded.bounded_deferral is True
    assert "no module named widgets" in bounded.reason
