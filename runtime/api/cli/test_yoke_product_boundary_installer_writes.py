from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory


REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_doc(root: Path, text: str) -> None:
    path = root / ".agents" / "skills" / "yoke" / "example.md"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")


def _only_surface(audit: inventory.TeachingAudit):
    rows = list(audit.surfaces)
    assert len(rows) == 1
    return rows[0]


def test_registry_contains_shepherd_and_qa_writer_surfaces():
    rows = {
        row.command_helper: row
        for row in inventory.generate_inventory(repo_root=REPO_ROOT)
    }

    assert rows["yoke qa requirement waive"].function_id == (
        "qa.requirement.waive"
    )
    assert rows["yoke shepherd verdict"].function_id == "shepherd.verdict.run"
    assert rows["yoke shepherd caveat-disposition"].function_id == (
        "shepherd.caveat_disposition.run"
    )


def test_teaching_audit_resolves_shepherd_verdict_writers(tmp_path: Path):
    _write_doc(
        tmp_path,
        "```bash\n"
        "yoke shepherd verdict --item YOK-20 --transition T "
        "--worker W --verdict READY\n"
        "yoke shepherd caveat-disposition --item YOK-20 --transition T "
        "--attempt 1 --caveat-num 1 --caveat-text fixed "
        "--disposition RESOLVED\n"
        "```\n",
    )

    audit = inventory.generate_teaching_audit(repo_root=tmp_path)
    by_command = {row.command_form: row for row in audit.surfaces}

    assert by_command["yoke shepherd verdict"].function_id == (
        "shepherd.verdict.run"
    )
    assert by_command["yoke shepherd caveat-disposition"].function_id == (
        "shepherd.caveat_disposition.run"
    )
    assert {row.drift_type for row in by_command.values()} == {None}


def test_teaching_audit_resolves_qa_requirement_waive(tmp_path: Path):
    _write_doc(
        tmp_path,
        "```bash\n"
        "yoke qa requirement waive --requirement-id 7 "
        "--rationale accepted --source operator --force\n"
        "```\n",
    )

    surface = _only_surface(inventory.generate_teaching_audit(repo_root=tmp_path))
    assert surface.command_form == "yoke qa requirement waive"
    assert surface.function_id == "qa.requirement.waive"
    assert surface.drift_type is None
