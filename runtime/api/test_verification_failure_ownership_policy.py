"""Doc regressions for verification-failure ownership and path-claim override discipline."""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()


def _read(rel_path: str) -> str:
    return (REPO / rel_path).read_text(encoding="utf-8")


def test_project_rules_define_current_item_verification_ownership():
    text = _read("AGENTS.md")

    assert "## Verification Failure Ownership" in text
    assert "Current-item verification failures belong to the current item" in text
    assert "planned path claim" in text
    assert "not a waiver" in text
    assert "Use dependency and claim reconciliation before override" in text
    assert "Do not use `path-claim-override` for a planned future claim" in text
    assert "explicit operator approval" in text


def test_lifecycle_verification_surfaces_reference_global_policy():
    surfaces = [
        _read(".agents/skills/yoke/advance/implementing/test-and-record.md"),
        _read(".agents/skills/yoke/conduct/dispatch-context-verify.md"),
        _read(".agents/skills/yoke/polish/verify-and-commit.md"),
        _read(".agents/skills/yoke/merge/conflict-handling.md"),
        _read(".agents/skills/yoke/usher/merge.md"),
    ]

    for text in surfaces:
        assert "planned path claim" in text
        assert "dependency or claim reconciliation" in text
        assert "Do not use `path-claim-override` for a planned future claim" in text
        assert "override is last resort" in text
        assert "explicit operator approval" in text
