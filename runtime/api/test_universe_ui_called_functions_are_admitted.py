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

from yoke_core.ui import asset_roster, function_proxy

#: `callFunction(client, "id", …)` and `sessionControlCall(context, "id", …)`
#: are the two shapes a static module uses to reach the proxy. The id is
#: always the first string argument after the client or context.
_CALL_SITE = re.compile(
    r"""(?:callFunction|sessionControlCall)\s*\(\s*[^,()]+,\s*["']([a-z_][\w.]*)["']""",
)

#: Some callers build the envelope themselves and name the id as a field.
_ENVELOPE_FIELD = re.compile(r"""\bfunction:\s*["']([a-z_][\w.]*)["']""")


def _called_function_ids() -> dict[str, set[str]]:
    """Map each function id the workbench calls to the modules calling it."""
    static = files("yoke_core.ui").joinpath("static")
    callers: dict[str, set[str]] = {}
    for name in asset_roster.ASSET_CONTENT_TYPES:
        if not name.endswith(".js"):
            continue
        text = static.joinpath(name).read_text()
        for function_id in _CALL_SITE.findall(text) + _ENVELOPE_FIELD.findall(text):
            callers.setdefault(function_id, set()).add(name)
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
