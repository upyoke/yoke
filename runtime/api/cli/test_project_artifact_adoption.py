"""One-time ownership adoption for legacy rendered project artifacts."""

from pathlib import Path

import pytest

from runtime.api.cli.test_project_artifact_reconciliation import _bundle, _preview
from yoke_cli.project_artifacts.validate import ProjectArtifactError, load_manifest
from yoke_cli.project_artifacts.writer import adopt_existing_plan, apply_plan


def test_adopt_existing_seeds_ownership_before_visible_template_apply(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "project"
    existing = repo / "ops/converge.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("#!/usr/bin/env python3\n# legacy render\n")
    existing.chmod(0o755)
    before = existing.read_bytes()
    bundle = _bundle(
        {
            "ops/converge.py": ("#!/usr/bin/env python3\n# fresh render\n", 0o755),
            "infra/program.py": ("# newly rendered\n", 0o644),
        }
    )
    entries, manifest, plan = _preview(repo, bundle)

    result = adopt_existing_plan(repo, bundle, entries, manifest, plan)

    assert result["adopted"] == ["ops/converge.py"]
    assert existing.read_bytes() == before
    assert not (repo / "infra/program.py").exists()
    adopted_manifest = load_manifest(repo)
    assert adopted_manifest is not None
    assert sorted(adopted_manifest["artifacts"]) == ["ops/converge.py"]

    refreshed_entries, refreshed_manifest, refreshed_plan = _preview(repo, bundle)
    assert [row["path"] for row in refreshed_plan["updates"]] == ["ops/converge.py"]
    assert [row["path"] for row in refreshed_plan["creates"]] == ["infra/program.py"]
    assert refreshed_plan["conflicts"] == []
    apply_plan(
        repo,
        bundle,
        refreshed_entries,
        refreshed_manifest,
        refreshed_plan,
    )
    assert existing.read_text() == "#!/usr/bin/env python3\n# fresh render\n"
    assert (repo / "infra/program.py").read_text() == "# newly rendered\n"
    assert _preview(repo, bundle)[2]["drift"] is False


def test_adopted_file_changed_before_apply_becomes_protected_conflict(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "project"
    existing = repo / "ops/converge.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("legacy render\n")
    existing.chmod(0o755)
    bundle = _bundle({"ops/converge.py": ("fresh render\n", 0o755)})
    entries, manifest, plan = _preview(repo, bundle)
    adopt_existing_plan(repo, bundle, entries, manifest, plan)

    existing.write_text("project edit after adoption\n")
    _entries, _manifest, changed = _preview(repo, bundle)

    assert changed["updates"] == []
    assert changed["conflicts"][0]["reason"] == "locally_modified"


def test_adopt_existing_refuses_when_manifest_already_exists(tmp_path: Path) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    bundle = _bundle({"ops/converge.py": ("fresh render\n", 0o755)})
    entries, manifest, plan = _preview(repo, bundle)
    apply_plan(repo, bundle, entries, manifest, plan)
    entries, manifest, plan = _preview(repo, bundle)

    with pytest.raises(ProjectArtifactError, match="no artifact manifest"):
        adopt_existing_plan(repo, bundle, entries, manifest, plan)
