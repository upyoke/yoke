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
    assert "require a live steering seat covering the project" in text


def test_lifecycle_verification_surfaces_reference_global_policy():
    surfaces = [
        _read(".agents/skills/yoke/implement/implementing/test-and-record.md"),
        _read(".agents/skills/yoke/conduct/dispatch-context-verify.md"),
        _read(".agents/skills/yoke/polish/verify-and-commit.md"),
        _read(".agents/skills/yoke/usher/merge-conflicts.md"),
        _read(".agents/skills/yoke/usher/merge.md"),
    ]

    home = _read(".yoke/docs/reference/agent-rules/verification.md")
    for text in surfaces:
        assert "claim" in text and "override" in text
        assert "reconcil" in text.lower()
        assert "current-item" in text.lower() or "current\nfailures" in text
        assert "future" in text or "planned" in text
    assert "planned path claim" in home
    assert "Use dependency and claim reconciliation before override" in home
    assert "Do not use `path-claim-override` for a planned future claim" in home
    assert "override is last resort" in home
    assert "requires a live steering seat covering the project" in home
