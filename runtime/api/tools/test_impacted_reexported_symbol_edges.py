"""Selecting the module that defines a name, not the one handing it out.

A test names the surface it imports from, which is rarely the file the
behaviour lives in. These cover the shapes the parser can follow — plain
re-export, several hops, aliases, star re-export — and the shapes it
cannot, where the answer has to be "no extra edge" rather than a guess.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools._impacted_import_index import direct_importer_tests
from yoke_core.tools.impacted_tests import build_import_index, select

from runtime.api.tools.test_impacted_tests import _tiny_repo, _write

_DEFINER = "runtime/api/definer.py"
_DEFINER_BODY = "def behaviour():\n    return 1\n"


def _selects(root: Path, changed: str, test_path: str) -> bool:
    return test_path in direct_importer_tests([changed], build_import_index(root))


def test_reexported_symbol_reaches_its_definer(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(root, "runtime/api/facade.py", "from runtime.api.definer import behaviour\n")
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.facade import behaviour\n\ndef test_it():\n    pass\n",
    )

    assert _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_several_hops_of_reexport_still_reach_the_definer(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(
        root, "runtime/api/registry.py", "from runtime.api.definer import behaviour\n"
    )
    _write(
        root, "runtime/api/runner.py", "from runtime.api.registry import behaviour\n"
    )
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.runner import behaviour\n\ndef test_it():\n    pass\n",
    )

    assert _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_an_alias_along_the_chain_is_followed(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(
        root,
        "runtime/api/facade.py",
        "from runtime.api.definer import behaviour as renamed\n",
    )
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.facade import renamed\n\ndef test_it():\n    pass\n",
    )

    assert _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_a_star_reexport_is_followed(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(root, "runtime/api/facade.py", "from runtime.api.definer import *\n")
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.facade import behaviour\n\ndef test_it():\n    pass\n",
    )

    assert _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_a_name_the_facade_redefines_stops_at_the_facade(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(
        root,
        "runtime/api/facade.py",
        "from runtime.api.definer import behaviour\n\n\ndef behaviour():\n    return 2\n",
    )
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.facade import behaviour\n\ndef test_it():\n    pass\n",
    )

    # The facade's own definition is what the test exercises, so the
    # definer earns no edge from this import.
    assert not _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_another_symbol_from_the_same_facade_pulls_nothing_extra(
    tmp_path: Path,
) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(root, "runtime/api/other.py", "def unrelated():\n    return 3\n")
    _write(
        root,
        "runtime/api/facade.py",
        "from runtime.api.definer import behaviour\n"
        "from runtime.api.other import unrelated\n",
    )
    _write(
        root,
        "runtime/api/test_unrelated.py",
        "from runtime.api.facade import unrelated\n\ndef test_it():\n    pass\n",
    )

    # The edge is the one symbol, never the facade's whole fan-in.
    assert not _selects(root, _DEFINER, "runtime/api/test_unrelated.py")


def test_a_reexport_cycle_terminates(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(
        root,
        "runtime/api/left.py",
        "from runtime.api.right import behaviour\n",
    )
    _write(
        root,
        "runtime/api/right.py",
        "from runtime.api.left import behaviour\n",
    )
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.left import behaviour\n\ndef test_it():\n    pass\n",
    )

    # Nothing in the cycle defines the name, so the walk ends without an
    # edge rather than circling — the index still builds.
    assert not _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_a_name_from_outside_the_tree_adds_no_edge(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from third_party.absent import behaviour\n\ndef test_it():\n    pass\n",
    )

    assert not _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_a_dynamically_bound_name_adds_no_edge(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    # The facade builds its surface at import time, which no static read
    # of the module can follow.
    _write(
        root,
        "runtime/api/facade.py",
        "import importlib\n\n"
        "behaviour = getattr(importlib.import_module('runtime.api.definer'), 'x')\n",
    )
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.facade import behaviour\n\ndef test_it():\n    pass\n",
    )

    # ``behaviour`` is bound by the facade, so the facade is the answer;
    # the definer is reached only by the module-level import edge, which
    # the string-literal reference already provides.
    assert not _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_the_definer_change_selects_the_test_end_to_end(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    _write(
        root, "runtime/api/registry.py", "from runtime.api.definer import behaviour\n"
    )
    _write(
        root, "runtime/api/runner.py", "from runtime.api.registry import behaviour\n"
    )
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.runner import behaviour\n\ndef test_it():\n    pass\n",
    )

    selection = select([_DEFINER], build_import_index(root), bounded=True)

    assert selection.full_sweep is False
    assert "runtime/api/test_behaviour.py" in selection.files


def test_a_later_import_wins_over_an_earlier_definition(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, _DEFINER, _DEFINER_BODY)
    # The import runs last, so it is what the facade hands out — the
    # earlier definition is dead by the time anything imports from here.
    _write(
        root,
        "runtime/api/facade.py",
        "def behaviour():\n    return 2\n\n\nfrom runtime.api.definer import behaviour\n",
    )
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.facade import behaviour\n\ndef test_it():\n    pass\n",
    )

    assert _selects(root, _DEFINER, "runtime/api/test_behaviour.py")


def test_a_package_init_reexports_its_own_submodule(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    definer = "runtime/api/pack/impl.py"
    _write(root, "runtime/api/pack/__init__.py", "from .impl import behaviour\n")
    _write(root, definer, _DEFINER_BODY)
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.pack import behaviour\n\ndef test_it():\n    pass\n",
    )

    # ``.impl`` inside ``pack/__init__.py`` is ``pack.impl``, not a
    # top-level ``impl`` — the package is the init module's own name.
    assert _selects(root, definer, "runtime/api/test_behaviour.py")


def test_a_nested_package_init_reexports_its_own_submodule(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    definer = "runtime/api/pack/inner/impl.py"
    _write(root, "runtime/api/pack/__init__.py", "")
    _write(root, "runtime/api/pack/inner/__init__.py", "from .impl import behaviour\n")
    _write(root, definer, _DEFINER_BODY)
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.pack.inner import behaviour\n\ndef test_it():\n    pass\n",
    )

    assert _selects(root, definer, "runtime/api/test_behaviour.py")


def test_a_relative_import_from_a_plain_module_still_resolves(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    definer = "runtime/api/pack/impl.py"
    _write(root, "runtime/api/pack/__init__.py", "")
    _write(root, "runtime/api/pack/facade.py", "from .impl import behaviour\n")
    _write(root, definer, _DEFINER_BODY)
    _write(
        root,
        "runtime/api/test_behaviour.py",
        "from runtime.api.pack.facade import behaviour\n\ndef test_it():\n    pass\n",
    )

    # A plain module's package is its parent, which this must keep right
    # while the init case is fixed.
    assert _selects(root, definer, "runtime/api/test_behaviour.py")
