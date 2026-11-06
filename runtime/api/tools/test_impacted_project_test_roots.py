"""Project Structure test-root resolution."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import impacted_project_test_roots as roots


def test_live_entries_are_normalized(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(roots, "default_project_for_directory", lambda _p: "platform")

    def _relay(_function, _payload):
        return {"entries": [{"attachment": "services/platform-svc/tests"}]}

    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay",
        _relay,
    )
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == ("services/platform-svc/tests/",)


def test_live_empty_falls_back_only_on_a_yoke_tree(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(roots, "_try_read", lambda _project: ())
    monkeypatch.setattr(roots, "default_project_for_directory", lambda _p: "yoke")
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == ()
    marker = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core"
    marker.mkdir(parents=True)
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == roots.YOKE_SEEDED_TEST_ROOTS


def test_failed_read_falls_back_only_on_a_yoke_tree(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(roots, "_try_read", lambda _project: None)
    monkeypatch.setattr(roots, "default_project_for_directory", lambda _p: "yoke")
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == ()
    marker = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core"
    marker.mkdir(parents=True)
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == roots.YOKE_SEEDED_TEST_ROOTS


def test_explicit_environment_project_without_checkout_binding(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_PROJECT", "selected")
    monkeypatch.setattr(roots, "default_project_for_directory", lambda _p: None)
    seen = []

    def read(project):
        seen.append(project)
        return ("selected-tests/",)

    monkeypatch.setattr(roots, "_try_read", read)
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == ("selected-tests/",)
    assert seen == ["selected"]


def _selector_tree(checkout: Path, test_root: str, count: int = 1) -> None:
    (checkout / "pkg").mkdir(parents=True)
    (checkout / "pkg/subject.py").write_text("VALUE = 1\n")
    tests = checkout / test_root
    tests.mkdir()
    (tests / "conftest.py").write_text(
        "import pytest\nfrom pkg.subject import VALUE\n"
        "@pytest.fixture\ndef value():\n    return VALUE\n"
    )
    for number in range(count):
        (tests / f"test_subject_{number}.py").write_text(
            "def test_subject(value):\n    assert value == 1\n"
        )
        (checkout / "pkg" / f"helper_{number}.py").write_text("VALUE = 2\n")


def test_index_and_selection_never_read_working_directory(monkeypatch, tmp_path):
    import os

    from yoke_core.tools.impacted_tests import build_import_index, is_test_file, select

    _selector_tree(tmp_path, "tests", count=200)
    for n in range(100):
        (tmp_path / "tests" / f"test_unrelated_{n}.py").write_text("def test_ok(): pass\n")
    calls = 0

    def getcwd():
        nonlocal calls
        calls += 1
        raise AssertionError("selection must use its explicit checkout")

    with monkeypatch.context() as patch:
        patch.setattr(os, "getcwd", getcwd)
        index = build_import_index(tmp_path)
        selected = select(["pkg/subject.py"], index)
        assert all(is_test_file(p, index.test_roots) for p in selected.files)
    assert calls == 0
    assert selected.files == tuple(
        sorted(f"tests/test_subject_{n}.py" for n in range(200))
    )
    assert selected.test_roots == index.test_roots


def test_each_index_keeps_its_checkout_roots_after_chdir(monkeypatch, tmp_path):
    from yoke_core.tools.impacted_tests import build_import_index, select

    first, second = tmp_path / "first", tmp_path / "second"
    _selector_tree(first, "checks")
    _selector_tree(second, "specs")
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(roots, "default_project_for_directory", lambda p: p.name)
    monkeypatch.setattr(
        roots, "_try_read", lambda p: {"first": ("checks/",), "second": ("specs/",)}[p]
    )
    monkeypatch.chdir(second)
    index = build_import_index(first)
    other = build_import_index(second)
    assert select(["pkg/subject.py"], index).files == ("checks/test_subject_0.py",)
    assert select(["pkg/subject.py"], other).files == ("specs/test_subject_0.py",)
    assert select(["docs/readme.md"], index).pytest_paths() == ("checks/",)
    monkeypatch.chdir(first)
    assert select(["docs/readme.md"], other).pytest_paths() == ("specs/",)


def test_selection_survives_deleted_working_directory(monkeypatch, tmp_path):
    import os

    from yoke_core.tools.impacted_tests import build_import_index, select

    checkout = tmp_path / "checkout"
    _selector_tree(checkout, "tests")
    deleted = tmp_path / "deleted"
    deleted.mkdir()
    original = Path.cwd()
    try:
        os.chdir(deleted)
        deleted.rmdir()
        index = build_import_index(checkout)
        selection = select(["pkg/subject.py"], index)
        assert selection.files == ("tests/test_subject_0.py",)
        assert select(["docs/readme.md"], index).pytest_paths() == index.test_roots
    finally:
        os.chdir(original)
