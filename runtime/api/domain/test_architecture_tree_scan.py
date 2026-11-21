"""The git-tree architecture scan classifies, resolves and names each edge."""

from __future__ import annotations

import pytest

from runtime.api.domain.architecture_edge_test_support import MODEL, SRC
from yoke_core.domain.architecture_tree_scan import (
    BaselineError,
    forbidden_edges,
    parse_baseline,
    render_baseline,
)

TREE = [f"{SRC}/low/a.py", f"{SRC}/mid/m.py", f"{SRC}/high/b.py", f"{SRC}/tests/t.py"]


def test_forbidden_and_omitted_pairs_are_named_with_their_rule():
    sources = {
        f"{SRC}/low/a.py": "from yoke_core.high import b\nimport yoke_core.mid.m\n",
        f"{SRC}/high/b.py": "from yoke_core.low.a import thing\nfrom yoke_core.mid import m\n",
        f"{SRC}/tests/t.py": "from yoke_core.high import b\n",
    }
    edges = forbidden_edges(MODEL, sources, TREE)
    assert [(e.path, e.imported_module, e.source_layer, e.imported_layer, e.rule)
            for e in edges] == [
        (f"{SRC}/low/a.py", "yoke_core.high", "low", "high", "forbidden_edges"),
        (f"{SRC}/low/a.py", "yoke_core.mid.m", "low", "mid", "may_depend_on"),
    ]
    assert "low.forbidden_edges lists high" in edges[0].describe()
    assert "low.may_depend_on omits mid" in edges[1].describe()


def test_imports_resolve_only_against_the_scanned_tree():
    sources = {f"{SRC}/low/a.py": "from yoke_core.high import gone\nimport json\n"}
    assert forbidden_edges(MODEL, sources, [f"{SRC}/low/a.py"]) == []


def test_baseline_round_trips_one_edge_per_line():
    sources = {f"{SRC}/low/a.py": "from yoke_core.high import b\nfrom yoke_core.high import c\n"}
    edges = forbidden_edges(MODEL, sources, TREE)
    text = render_baseline(edges)
    assert text.count("\n") == len(edges) + 2
    assert parse_baseline(text) == {edge.key for edge in edges}
    assert render_baseline([]) == "[]\n"


@pytest.mark.parametrize("text", ["{", "{}", '[{"path": "a.py"}]'])
def test_malformed_baseline_is_named(text):
    with pytest.raises(BaselineError, match="forbidden-edge-baseline.json"):
        parse_baseline(text)
