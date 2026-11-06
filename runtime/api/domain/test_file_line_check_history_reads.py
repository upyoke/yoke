"""Passing changed files need no historical blobs in a partial clone."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import file_line_check as core
from yoke_harness.git_hooks import file_line_check as harness


@pytest.mark.parametrize("checker", [core, harness])
@pytest.mark.parametrize("staged", [False, True])
@pytest.mark.parametrize("kind,new", [("AUTHORED", 350), ("TEMPORARY_EXCEPTION", 12), ("GENERATED", 900)])
def test_passing_changes_do_not_read_baseline(tmp_path, monkeypatch, checker, staged, kind, new):
    paths = tuple(f"file_{i}.py" for i in range(2100))
    monkeypatch.setattr(checker, "resolve_file_line_git_scope", lambda *a: SimpleNamespace(item_base_sha="base", inherited_paths=()))
    monkeypatch.setattr(checker, "changed_scope_for_check", lambda *a, **kw: SimpleNamespace(paths=paths, coverage_sentence=lambda: "all paths"))
    monkeypatch.setattr(checker, "resolved_policy", lambda *a: SimpleNamespace(limit=350))
    monkeypatch.setattr(checker, "_classify_path_with_policy", lambda *a, **kw: getattr(checker.Classification, kind))
    monkeypatch.setattr(checker, "staged_new_count", lambda *a, **kw: new)
    monkeypatch.setattr(checker, "head_new_count", lambda *a, **kw: new)

    def baseline_read(*args, **kwargs):
        pytest.fail("passing files must not fetch historical blobs")

    monkeypatch.setattr(checker, "git_show_line_count", baseline_read)
    verdict = checker.changed_files_check(repo_root=tmp_path, base="main", staged=staged)
    assert verdict.ok
    assert verdict.hard_fails == verdict.warnings == verdict.pre_existing == []


@pytest.mark.parametrize("checker", [core, harness])
@pytest.mark.parametrize("old,new,ok", [(400, 401, False), (400, 399, True), (350, 351, False)])
def test_oversized_changes_preserve_baseline_counts(tmp_path, monkeypatch, checker, old, new, ok):
    monkeypatch.setattr(checker, "_classify_path_with_policy", lambda *a, **kw: checker.Classification.AUTHORED)
    monkeypatch.setattr(checker, "head_new_count", lambda *a, **kw: new)
    monkeypatch.setattr(checker, "git_show_line_count", lambda *a, **kw: old)
    change = checker._build_changed_file("big.py", repo_root=tmp_path, base="main", staged=False, policy=SimpleNamespace(limit=350))
    assert change.old_line_count == old
    assert change.new_line_count == new
    assert change.delta == new - old
    hard, warning, _ = checker.classify_change(old=old, new=new, limit=350, classification=change.classification)
    assert hard is not ok
    assert warning is ok
