from yoke_core.domain.verify_overlap import main


def test_verify_overlap_passes_without_conflicts(tmp_path, capsys):
    plan = tmp_path / "worktree-plan.md"
    plan.write_text(
        """## Worktree: alpha
Files touched:
  - src/a.py
  - src/b.py

## Worktree: beta
Files touched:
  - src/c.py

## Dependency groups
  - ui: docs/ui.md
""",
        encoding="utf-8",
    )

    rc = main([str(plan)])

    captured = capsys.readouterr()
    assert rc == 0
    assert "PASS" in captured.out


def test_verify_overlap_reports_file_conflict(tmp_path, capsys):
    plan = tmp_path / "worktree-plan.md"
    plan.write_text(
        """## Worktree: alpha
Files touched:
  - src/shared.py (edit)

## Worktree: beta
Files touched:
  - src/shared.py
""",
        encoding="utf-8",
    )

    rc = main([str(plan)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "OVERLAP: src/shared.py" in captured.err


def test_verify_overlap_reports_dependency_group_conflict(tmp_path, capsys):
    plan = tmp_path / "worktree-plan.md"
    plan.write_text(
        """## Worktree: alpha
Files touched:
  - src/a.py
Generated files (auto-resolve on merge):
  - package-lock.json

## Worktree: beta
Files touched:
  - src/b.py

## Dependency groups
  - runtime: src/a.py, src/b.py
""",
        encoding="utf-8",
    )

    rc = main([str(plan)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "LOGICAL OVERLAP" in captured.err
