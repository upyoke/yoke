"""A file named by path is reachable from the file naming it.

Rosters like the field-note importing-consumer list and the
workspace-anchored writer list name the files they govern as
repo-relative path strings. A static-content test names its subject a
segment at a time instead — ``root / "pkg" / "thing.py"`` — so the whole
path is never written down and only the bare name is. Without edges from
both shapes, editing a named file leaves the test reading it unreachable,
and CI is the first thing to notice — which is exactly the selector
defect this covers.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools._impacted_import_index import (
    build_import_index,
    reachable_tests,
)


def _write(root: Path, rel: str, body: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _tree(root: Path) -> None:
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/governed.py", "VALUE = 1\n")
    # The roster names the governed file by path, never importing it.
    _write(
        root,
        "pkg/roster.py",
        'GOVERNED = ("pkg/governed.py",)\n',
    )
    _write(
        root,
        "tests/test_roster.py",
        "from pkg.roster import GOVERNED\n\n\ndef test_roster():\n"
        "    assert GOVERNED\n",
    )


def test_path_literal_links_the_named_file_to_its_roster(tmp_path: Path) -> None:
    _tree(tmp_path)
    index = build_import_index(tmp_path)
    assert "pkg/roster.py" in index.importers.get("pkg.governed", set())


def test_editing_a_named_file_reaches_the_roster_test(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "yoke_core.tools._impacted_import_index.current_test_roots",
        lambda: ("tests/",),
    )
    _tree(tmp_path)
    index = build_import_index(tmp_path)
    reached = reachable_tests(["pkg/governed.py"], index)
    assert reached is not None
    assert "tests/test_roster.py" in reached


def test_a_path_literal_naming_no_real_file_is_dropped(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/roster.py", 'MISSING = ("pkg/absent.py",)\n')
    index = build_import_index(tmp_path)
    # Unlike a dotted literal, an unresolved path is not kept as an inert
    # key — nothing could ever match it.
    assert "pkg/absent.py" not in index.importers
    assert "pkg.absent" not in index.importers


def test_project_local_check_is_named_by_its_import_namespace() -> None:
    """A ``.yoke/doctor/`` check is reachable by the name tests import."""
    from yoke_core.tools._impacted_import_index import module_name_for

    assert (
        module_name_for(".yoke/doctor/check_field_note_coherence.py")
        == "yoke_project_checks.check_field_note_coherence"
    )


def test_roster_chain_reaches_the_test_that_guards_it(
    tmp_path: Path, monkeypatch
) -> None:
    # The full shape this selector defect took in the live tree: a
    # governed file, a project-local check naming it by path, and the
    # test importing that check by its namespace.
    monkeypatch.setattr(
        "yoke_core.tools._impacted_import_index.current_test_roots",
        lambda: ("tests/",),
    )
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/governed.py", "VALUE = 1\n")
    _write(
        tmp_path,
        ".yoke/doctor/check_roster.py",
        'GOVERNED = ("pkg/governed.py",)\n',
    )
    _write(
        tmp_path,
        "tests/test_roster_check.py",
        "from yoke_project_checks.check_roster import GOVERNED\n\n\n"
        "def test_roster():\n    assert GOVERNED\n",
    )
    index = build_import_index(tmp_path)
    reached = reachable_tests(["pkg/governed.py"], index)
    assert reached is not None
    assert "tests/test_roster_check.py" in reached


def _assembled_reader_tree(root: Path) -> None:
    """A test that names its subject by its bare file name only."""
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/teaching.py", 'PROSE = "the current phrasing"\n')
    _write(root, "pkg/conftest.py", "")
    _write(root, "other/__init__.py", "")
    _write(root, "other/conftest.py", "")
    _write(
        root,
        "tests/test_teaching.py",
        "from pathlib import Path\n\n"
        "_ROOT = Path(__file__).resolve().parents[1]\n"
        '_SUBJECT = _ROOT / "pkg" / "teaching.py"\n'
        '_AMBIGUOUS = _ROOT / "pkg" / "conftest.py"\n\n\n'
        "def test_teaching():\n"
        '    assert "current" in _SUBJECT.read_text()\n'
        "    assert _AMBIGUOUS.exists()\n",
    )


def test_a_bare_file_name_links_the_reader_that_assembled_it(tmp_path: Path) -> None:
    _assembled_reader_tree(tmp_path)

    index = build_import_index(tmp_path)

    assert "tests/test_teaching.py" in index.importers.get("pkg.teaching", set())


def test_an_ambiguous_bare_name_links_nothing(tmp_path: Path) -> None:
    """One literal must not widen to every package carrying that name."""
    _assembled_reader_tree(tmp_path)

    index = build_import_index(tmp_path)

    for module in ("pkg.conftest", "other.conftest"):
        assert "tests/test_teaching.py" not in index.importers.get(module, set())


def test_editing_an_assembled_subject_reaches_its_reader(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "yoke_core.tools._impacted_import_index.current_test_roots",
        lambda: ("tests/",),
    )
    _assembled_reader_tree(tmp_path)
    index = build_import_index(tmp_path)

    reached = reachable_tests(["pkg/teaching.py"], index)

    assert reached is not None
    assert "tests/test_teaching.py" in reached
