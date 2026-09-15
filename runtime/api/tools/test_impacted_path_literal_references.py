"""A file named by path is reachable from the file naming it.

Rosters like the field-note importing-consumer list and the
workspace-anchored writer list name the files they govern as
repo-relative path strings. A test that loads a script from disk names
its subject a segment at a time instead — ``root / "pkg" / "thing.py"``
— so the whole path is written nowhere and must be read back out of the
composition; reading only the bare name leaves an ambiguous one, such as
this repository's three ``install.py`` files, naming nothing. Without
edges from both shapes, editing a named file leaves the test reading it
unreachable, and CI is the first thing to notice — which is exactly the
selector defect this covers.
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


def test_a_shared_name_links_only_the_package_it_was_composed_under(
    tmp_path: Path,
) -> None:
    """One reference must not widen to every package carrying that name."""
    _assembled_reader_tree(tmp_path)

    index = build_import_index(tmp_path)

    assert "tests/test_teaching.py" in index.importers.get("pkg.conftest", set())
    assert "tests/test_teaching.py" not in index.importers.get("other.conftest", set())


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


def _installer_tree(root: Path) -> Path:
    """The live ambiguity: one installer test, three ``install.py`` files.

    The test's own source is copied from this checkout, so the reference
    under test is the composition the real file actually writes rather
    than a restatement of it.
    """
    repo_root = Path(__file__).resolve().parents[3]
    subject = "runtime/api/cli/test_public_installer_shim.py"
    _write(root, subject, (repo_root / subject).read_text(encoding="utf-8"))
    for rel in (
        "packaging/public-installer/install.py",
        "packages/yoke-cli/src/yoke_cli/commands/adapters/install.py",
        "packages/yoke-core/src/yoke_core/api/routes/install.py",
    ):
        _write(root, rel, "VERSION = 1\n")
    return root


def test_editing_the_installer_reaches_the_test_that_loads_it(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "yoke_core.tools._impacted_import_index.current_test_roots",
        lambda: ("runtime/",),
    )
    _installer_tree(tmp_path)

    index = build_import_index(tmp_path)

    reached = reachable_tests(["packaging/public-installer/install.py"], index)
    assert reached is not None
    assert "runtime/api/cli/test_public_installer_shim.py" in reached


def test_a_composed_path_names_only_the_file_it_spells(tmp_path: Path) -> None:
    """Complete path evidence, not the basename the three files share."""
    _installer_tree(tmp_path)

    index = build_import_index(tmp_path)

    subject = "runtime/api/cli/test_public_installer_shim.py"
    assert subject in index.importers.get("packaging.public-installer.install", set())
    for other in (
        "yoke_cli.commands.adapters.install",
        "yoke_core.api.routes.install",
    ):
        assert subject not in index.importers.get(other, set())


def test_a_composition_below_the_repository_root_resolves_by_its_whole_tail(
    tmp_path: Path,
) -> None:
    """A path composed from a directory anchor still names one file."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/nested/subject.py", "VALUE = 1\n")
    _write(tmp_path, "other/nested/subject.py", "VALUE = 2\n")
    _write(
        tmp_path,
        "tests/test_nested.py",
        "from pathlib import Path\n\n"
        "_HERE = Path(__file__).resolve().parent\n"
        '_SUBJECT = _HERE / "nested" / "subject.py"\n\n\n'
        "def test_nested():\n    assert _SUBJECT\n",
    )

    index = build_import_index(tmp_path)

    # ``nested/subject.py`` is carried by two directories, so the tail
    # names no single file and links nothing.
    for module in ("pkg.nested.subject", "other.nested.subject"):
        assert "tests/test_nested.py" not in index.importers.get(module, set())


def test_a_composition_naming_a_unique_tail_links_that_file(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/nested/subject.py", "VALUE = 1\n")
    _write(
        tmp_path,
        "tests/test_nested.py",
        "from pathlib import Path\n\n"
        "_HERE = Path(__file__).resolve().parent\n"
        '_SUBJECT = _HERE / "nested" / "subject.py"\n\n\n'
        "def test_nested():\n    assert _SUBJECT\n",
    )

    index = build_import_index(tmp_path)

    assert "tests/test_nested.py" in index.importers.get("pkg.nested.subject", set())


def test_a_composition_outside_the_repository_links_nothing(tmp_path: Path) -> None:
    """An absolute anchor is read, so its tail is not a repository path."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/subject.py", "VALUE = 1\n")
    # A second file of the same name, so the bare-name rule cannot link
    # this reader and the composition is the only thing under test.
    _write(tmp_path, "other/subject.py", "VALUE = 2\n")
    _write(
        tmp_path,
        "tests/test_outside.py",
        "from pathlib import Path\n\n"
        '_ELSEWHERE = Path("/usr/local/share") / "pkg" / "subject.py"\n'
        '_ABSENT = Path(__file__).parent / "pkg" / "missing.py"\n\n\n'
        "def test_outside():\n    assert _ELSEWHERE or _ABSENT\n",
    )

    index = build_import_index(tmp_path)

    assert "tests/test_outside.py" not in index.importers.get("pkg.subject", set())
    assert "pkg.missing" not in index.importers


def test_a_dynamic_segment_leaves_only_the_name_it_wrote(tmp_path: Path) -> None:
    """An unresolved component keeps the conservative reading."""
    _installer_tree(tmp_path)
    _write(
        tmp_path,
        "runtime/api/cli/test_chosen.py",
        "from pathlib import Path\n\n"
        "_ROOT = Path(__file__).resolve().parents[3]\n"
        '_CHOSEN = _ROOT / chosen_dir() / "install.py"\n\n\n'
        'def chosen_dir():\n    return "packaging/public-installer"\n\n\n'
        "def test_chosen():\n    assert _CHOSEN\n",
    )

    index = build_import_index(tmp_path)

    # Only the ambiguous bare name survives the dynamic segment, so this
    # reader links to none of the three files carrying that name.
    for module in (
        "packaging.public-installer.install",
        "yoke_cli.commands.adapters.install",
        "yoke_core.api.routes.install",
    ):
        assert "runtime/api/cli/test_chosen.py" not in index.importers.get(
            module, set()
        )
