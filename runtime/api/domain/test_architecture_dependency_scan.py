"""Tests for ``architecture_dependency_scan``: pure-function AST import
extraction used by snapshot enrichment and architecture HCs.

AC-5 (Python import/dependency scan records import edges for ``.py``
files as JSON objects with ``source_module``, ``imported_module``, and
``imported_name``).
"""

from __future__ import annotations

import pytest

from yoke_core.domain import architecture_dependency_scan as scan


SOURCE_PATH = "packages/yoke-core/src/yoke_core/domain/foo.py"


class TestPathToModule:
    @pytest.mark.parametrize("path,module", [
        (SOURCE_PATH, "yoke_core.domain.foo"),
        ("packages/yoke-core/src/yoke_core/__init__.py", "yoke_core"),
        ("foo.py", "foo"),
        ("__init__.py", ""),
        ("docs/OVERVIEW.md", "docs/OVERVIEW.md"),  # non-py passes through
    ])
    def test_dotted_module_name(self, path, module):
        assert scan.path_to_module(path) == module


class TestExtractEdges:
    def test_plain_import_emits_module_and_alias_name(self):
        src = "import json\nimport os\n"
        result = scan.extract_edges(src, SOURCE_PATH)
        assert result.error is None
        assert result.edges == [
            {"source_module": "yoke_core.domain.foo",
             "imported_module": "json", "imported_name": "json"},
            {"source_module": "yoke_core.domain.foo",
             "imported_module": "os", "imported_name": "os"},
        ]

    def test_import_as_uses_alias_for_name(self):
        src = "import numpy as np\n"
        result = scan.extract_edges(src, "p.py")
        assert result.edges == [
            {"source_module": "p", "imported_module": "numpy",
             "imported_name": "np"},
        ]

    def test_dotted_import_records_full_module(self):
        src = "import yoke_core.domain.bar\n"
        result = scan.extract_edges(src, "p.py")
        assert result.edges == [
            {"source_module": "p",
             "imported_module": "yoke_core.domain.bar",
             "imported_name": "yoke_core"},
        ]

    def test_from_import_emits_member(self):
        src = "from yoke_core.domain.bar import baz, qux\n"
        result = scan.extract_edges(src, "p.py")
        assert result.edges == [
            {"source_module": "p",
             "imported_module": "yoke_core.domain.bar",
             "imported_name": "baz"},
            {"source_module": "p",
             "imported_module": "yoke_core.domain.bar",
             "imported_name": "qux"},
        ]

    def test_from_import_star(self):
        src = "from yoke_core.domain.bar import *\n"
        result = scan.extract_edges(src, "p.py")
        assert result.edges == [
            {"source_module": "p",
             "imported_module": "yoke_core.domain.bar",
             "imported_name": "*"},
        ]

    def test_relative_from_import_resolves_through_source_package(self):
        # source = yoke_core.domain.foo; "from .bar import baz" -> yoke_core.domain.bar
        src = "from .bar import baz\n"
        result = scan.extract_edges(src, SOURCE_PATH)
        assert result.edges == [
            {"source_module": "yoke_core.domain.foo",
             "imported_module": "yoke_core.domain.bar",
             "imported_name": "baz"},
        ]

    def test_relative_from_package_import_resolves_imported_module(self):
        src = "from . import sibling\n"
        result = scan.extract_edges(src, SOURCE_PATH)
        assert result.edges == [
            {"source_module": "yoke_core.domain.foo",
             "imported_module": "yoke_core.domain.sibling",
             "imported_name": "sibling"},
        ]

    def test_relative_from_double_dot_walks_two_levels(self):
        # source = yoke_core.domain.foo; "from ..engines import x" -> yoke_core.engines
        src = "from ..engines import x\n"
        result = scan.extract_edges(src, SOURCE_PATH)
        assert result.edges == [
            {"source_module": "yoke_core.domain.foo",
             "imported_module": "yoke_core.engines",
             "imported_name": "x"},
        ]

    def test_excessive_relative_level_is_dropped_not_raised(self):
        # 5 leading dots vs 4 parts in source module: out-of-package
        # relative import is silently skipped rather than crashing the
        # scan (fault-tolerance per Issue 3).
        src = "from ..... import x\n"
        result = scan.extract_edges(src, SOURCE_PATH)
        assert result.error is None
        assert result.edges == []

    def test_syntax_error_surfaces_via_result_not_raised(self):
        """Per AC-21 / Issue 3: AST parse failures degrade gracefully —
        the scanner returns a ScanResult with error set and edges empty
        instead of raising, so Doctor can record HC-architecture-scan-error
        and continue scanning other paths."""
        src = "def broken(\n"  # missing closing paren / body
        result = scan.extract_edges(src, "p.py")
        assert result.error is not None
        assert "SyntaxError" in result.error
        assert result.edges == []

    def test_top_level_only_no_nested_walk(self):
        """``ast.walk`` is depth-traversal — confirm the scanner records
        imports at every depth (function-local imports show up too).
        This is the intended shape: HCs catch nested imports that hide
        forbidden edges from a shallow scan."""
        src = (
            "def f():\n"
            "    import requests\n"
        )
        result = scan.extract_edges(src, "p.py")
        assert result.edges == [
            {"source_module": "p", "imported_module": "requests",
             "imported_name": "requests"},
        ]

    def test_imported_module_attribute_use_emits_guardable_symbol(self):
        src = "import sqlite3\nconn = sqlite3.connect(':memory:')\n"
        result = scan.extract_edges(src, SOURCE_PATH)
        assert {
            "source_module": "yoke_core.domain.foo",
            "imported_module": "sqlite3",
            "imported_name": "connect",
        } in result.edges

    def test_import_alias_attribute_use_uses_original_module(self):
        src = "import sqlite3 as db\nconn = db.connect(':memory:')\n"
        result = scan.extract_edges(src, "p.py")
        assert {
            "source_module": "p",
            "imported_module": "sqlite3",
            "imported_name": "connect",
        } in result.edges
