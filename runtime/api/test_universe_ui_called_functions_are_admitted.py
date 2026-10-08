"""Every function the workbench calls must be one this server admits.

The proxy's rosters are closed by design, which is what makes traversal
impossible — but closed also means they drift silently: a page gains a read,
nobody adds it, and the page renders a 403 where its content belongs while
every test still passes. That shape shipped three times at once (the Profile
page's five cards, both Packs sections, the Architecture health panel), so
the roster is checked against its callers rather than by hand.
"""

from __future__ import annotations

import re
from importlib.resources import files

import pytest

from runtime.api.universe_ui_server_test_support import (
    _TOKEN,
    ui_client as ui_client,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import lookup
from yoke_core.ui import function_proxy

#: Direct calls and read helpers whose id follows the client/context.
_CALL_SITE = re.compile(
    r"""(?:callFunction|sessionControlCall|readCase|readOptionalCase|call)"""
    r"""\s*\(\s*[^,()]+,\s*["']([a-z_]\w*(?:\.\w+)+)["']""",
)

#: Section loaders pass the id after both context and panel/scope.
_SECTION_CALL = re.compile(
    r"""(?:loadSection|loadProjectCalls)\s*\(\s*[^,()]+,\s*[^,()]+,"""
    r"""\s*["']([a-z_]\w*(?:\.\w+)+)["']""",
)

#: Scoped loaders and explicit envelopes store the id in a field.
_ENVELOPE_FIELD = re.compile(
    r"""\b(?:function|functionId):\s*["']([a-z_]\w*(?:\.\w+)+)["']"""
)

#: Small wrappers accept an id first; constants/ternaries feed dynamic calls.
_INDIRECT_CALL = re.compile(
    r"""(?:read|mutation|readCalls)\s*\(\s*["']([a-z_]\w*(?:\.\w+)+)["']"""
)
_ID_ASSIGNMENT = re.compile(r"\b(?:functionId|[A-Z_]*FUNCTION)\s*=([^;]+);")
_ID_LITERAL = re.compile(r"""["']([a-z_]\w*(?:\.\w+)+)["']""")


def _ids_in_source(text: str) -> set[str]:
    ids = set()
    for pattern in (_CALL_SITE, _SECTION_CALL, _ENVELOPE_FIELD, _INDIRECT_CALL):
        ids.update(pattern.findall(text))
    for assignment in _ID_ASSIGNMENT.findall(text):
        ids.update(_ID_LITERAL.findall(assignment))
    # Registered ids also cover wrappers, computed call selections, and object
    # arguments that the bounded call-site expressions above cannot parse.
    ids.update(value for value in _ID_LITERAL.findall(text) if lookup(value))
    return ids


def _called_function_ids() -> dict[str, set[str]]:
    """Map each function id the workbench calls to the modules calling it."""
    static = files("yoke_core.ui").joinpath("static")
    register_all_handlers()
    callers: dict[str, set[str]] = {}
    for source in static.iterdir():
        if not source.name.endswith(".js"):
            continue
        for function_id in _ids_in_source(source.read_text()):
            callers.setdefault(function_id, set()).add(source.name)
    return callers


def test_every_called_function_is_on_a_roster():
    admitted = (
        function_proxy.UI_READ_FUNCTION_ALLOWLIST
        | function_proxy.UI_MUTATION_FUNCTION_ALLOWLIST
    )
    missing = {
        function_id: sorted(callers)
        for function_id, callers in _called_function_ids().items()
        if function_id not in admitted
    }
    assert not missing, (
        "these functions are called by served modules but refused by the "
        f"proxy, so their pages render 403 instead of content: {missing}"
    )


def test_the_scan_finds_the_call_sites_it_is_guarding():
    """A regex that matched nothing would make the check above vacuous."""
    called = _called_function_ids()
    assert len(called) > 40, f"only found {len(called)} call sites"
    assert "items.search.run" in called
    assert "profile.get" in called
    assert called["universe.level_capacity.get"] == {"universe_views_levels.js"}
    assert "machine.detail" in called
    assert "overview.module.restore" in called
    assert "ui_preferences.search_history.record" in called


def test_missing_level_capacity_entry_fails_the_roster_check(monkeypatch):
    monkeypatch.setattr(
        function_proxy,
        "UI_READ_FUNCTION_ALLOWLIST",
        function_proxy.UI_READ_FUNCTION_ALLOWLIST - {"universe.level_capacity.get"},
    )
    with pytest.raises(AssertionError, match=r"universe\.level_capacity\.get"):
        test_every_called_function_is_on_a_roster()


def test_level_capacity_read_passes_through_the_local_ui_proxy(ui_client, test_db):
    response = ui_client.post(
        f"/api/functions/call?token={_TOKEN}",
        json={"function": "universe.level_capacity.get", "payload": {}},
    )
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["success"] is True, envelope
    result = envelope["result"]
    assert result["source"] == "default"
    assert [level["name"] for level in result["levels"]] == [
        "INTERN",
        "JUNIOR",
        "SENIOR",
        "PRINCIPAL",
    ]
    assert all(level["glyph"] and level["options"] for level in result["levels"])
    assert any(project["project"] == "yoke" for project in result["projects"])
