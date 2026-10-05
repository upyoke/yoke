"""Large surveys reuse pure parsing and owner facts without losing contacts."""

from __future__ import annotations

from itertools import product
from pathlib import PurePosixPath
from types import SimpleNamespace

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import conflict_survey as survey_module
from yoke_core.domain import conflict_survey_worktree_paths as worktree_module
from yoke_core.domain import conflict_survey_declared_paths as declared
from yoke_core.domain.conflict_survey_models import ConflictMatch


def _reference_overlap(left, right):
    left_path, right_path = PurePosixPath(left), PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def test_path_comparison_preserves_lexical_ancestry_and_anchors():
    paths = (
        "",
        ".",
        "./",
        "src",
        "src/",
        "src/a.py",
        "src/a.py/child",
        "src-other/a.py",
        "./src/a.py",
        "src//a.py",
        "src/../a.py",
        "..",
        "../a.py",
        "/",
        "/src",
        "/src/a.py",
        "//",
        "//src/a.py",
    )
    for left, right in product(paths, repeat=2):
        assert declared.path_scopes_overlap(left, right) == _reference_overlap(
            left,
            right,
        ), (left, right)


def test_large_scope_parses_each_distinct_path_once(monkeypatch):
    paths = tuple(f"src/module_{index}.py" for index in range(214))
    parsed = []

    def parse(path):
        parsed.append(path)
        return PurePosixPath(path)

    declared._scope_parts.cache_clear()
    monkeypatch.setattr(declared, "PurePosixPath", parse)
    try:
        assert declared.matching_scopes(paths, paths) == paths
        assert parsed == list(paths)
    finally:
        declared._scope_parts.cache_clear()


def test_absent_worktree_starts_no_git_process(monkeypatch, tmp_path):
    (tmp_path / "absent-file").write_text("not a directory")

    def unexpected(*args, **kwargs):
        raise AssertionError("absent worktree must not launch git")

    monkeypatch.setattr(worktree_module.subprocess, "run", unexpected)
    assert worktree_module.git_touched_paths(str(tmp_path / "absent"), "main") == []
    assert (
        worktree_module.git_touched_paths(str(tmp_path / "absent-file"), "main") == []
    )


def test_existing_worktree_keeps_all_three_best_effort_reads(monkeypatch, tmp_path):
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(worktree_module.subprocess, "run", run)
    assert worktree_module.git_touched_paths(str(tmp_path), "main") == []
    assert [command[3:] for command in commands] == [
        ["diff", "--name-only", "main...HEAD"],
        ["diff", "--name-only", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ]


def test_coordination_reads_once_per_owner_and_preserves_all_paths(monkeypatch):
    item_id = 91
    owners = (92, 93, 94, None)
    contacts = [
        ConflictMatch("path_claim", owner, f"src/{index}.py", "active", "contact")
        for owner in owners
        for index in range(214)
    ]
    monkeypatch.setattr(survey_module, "_item", lambda *args: {"id": item_id})
    monkeypatch.setattr(
        survey_module, "direct_workflow_blockers", lambda *a, **k: contacts
    )
    coordination_reads, serial_reads = [], []

    def coordinated(conn, *, item_a_id, item_b_id):
        coordination_reads.append(item_b_id)
        return item_b_id == owners[0]

    def serial(conn, *, dependent_item_id, blocking_item_id):
        serial_reads.append(dependent_item_id)
        return dependent_item_id == owners[1]

    monkeypatch.setattr(survey_module, "items_are_coordination_only", coordinated)
    monkeypatch.setattr(survey_module, "has_forward_serial_edge", serial)
    result = survey_module.survey_conflicts(None, item_id=item_id, touch_paths=["src"])
    assert set(result.blockers) == {
        row for row in contacts if row.owner_item_id in owners[2:]
    }
    assert sorted(coordination_reads) == list(owners[:3])
    assert sorted(serial_reads) == list(owners[1:3])


def test_large_survey_matches_original_blockers(test_db, monkeypatch):
    item_id, other_id = 231, 232
    paths = [f"src/module_{index}.py" for index in range(214)]
    insert_item(test_db, id=item_id, workflow_id="dash")
    insert_item(
        test_db,
        id=other_id,
        workflow_id="issue",
        spec="## File Budget\n" + "\n".join(f"- `{path}`" for path in paths),
    )
    optimized = survey_module.survey_conflicts(
        test_db, item_id=item_id, touch_paths=paths
    )
    monkeypatch.setattr(declared, "path_scopes_overlap", _reference_overlap)
    reference = survey_module.survey_conflicts(
        test_db, item_id=item_id, touch_paths=paths
    )
    assert optimized.blockers == reference.blockers
    assert optimized.fingerprint == reference.fingerprint
    assert len(optimized.blockers) == len(paths)
