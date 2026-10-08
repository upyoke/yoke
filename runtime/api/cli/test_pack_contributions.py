"""Disposable consumers exercise real scaffold rendering and co-owned updates."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.packs import runner
from yoke_cli.packs import relink
from yoke_cli.packs.merge import plan_get, plan_update
from yoke_cli.packs.receipt import load_receipt
from yoke_cli.packs.runner_support import _validate_bundle
from yoke_cli.project_install.managed_markdown import apply_managed_markdown
from yoke_contracts.project_contract.managed_block import block_span, render_block
from yoke_core.domain import pack_catalog

ROOT = Path(__file__).resolve().parents[3]
SLUG = "webapp-scaffold"


@pytest.fixture
def scaffold(monkeypatch):
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *a, **k: SimpleNamespace(id=9, slug="sample"),
    )
    values = {
        "project_name": "sample",
        "project_slug": "sample",
        "project_display_name": "Sample",
        "project_description": "A sample app",
        "api_port": "8000",
        "web_port": "3000",
    }
    bundle = pack_catalog.build_pack_bundle(
        None, project="sample", pack=SLUG, render_values=values
    )
    _validate_bundle(bundle)
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *a: None)
    monkeypatch.setattr(runner, "_report_receipt", lambda *a, **k: {"reported": True})

    def fetch(project, pack, *, version=None, render_values=None, **kwargs):
        if version is None or version == bundle["version"]:
            return bundle
        return pack_catalog.build_pack_bundle(
            None,
            project=project,
            pack=pack,
            version=version,
            render_values=render_values or values,
        )

    monkeypatch.setattr(runner, "_fetch_bundle", fetch)
    return bundle


def operation(root, *, action="get", apply=False, **kwargs):
    return runner.run_pack_operation(
        root,
        project="sample",
        pack=SLUG,
        operation=action,
        apply=apply,
        allow_missing_tools=True,
        **kwargs,
    )


def guidance(root, body="Yoke rules", records=None):
    return apply_managed_markdown(
        root,
        {
            "blocks": {"rules": body},
            "targets": [{"path": "AGENTS.md", "block": "rules"}],
        },
        records,
    )[0]


@pytest.mark.parametrize("existing", [False, True])
def test_real_scaffold_install_refresh_and_update_preserve_project_bytes(
    tmp_path, scaffold, monkeypatch, existing
):
    custom = "# Project notes\r\nKeep this exact text.\r\n"
    ignores = "# Project ignores\r\ncustomer-secrets/\r\n"
    if existing:
        (tmp_path / "AGENTS.md").write_bytes(custom.encode())
        (tmp_path / ".gitignore").write_bytes(ignores.encode())
    records = guidance(tmp_path)
    before = (tmp_path / "AGENTS.md").read_bytes()
    preview = operation(tmp_path)
    assert preview["conflict_count"] == 0
    assert not (tmp_path / ".yoke/packs.json").exists()
    applied = operation(tmp_path, apply=True)
    assert applied["plans"] == preview["plans"]
    assert applied["applied"]
    text = (tmp_path / "AGENTS.md").read_bytes()
    assert text.startswith(before)
    if existing:
        assert (tmp_path / ".gitignore").read_bytes().startswith(ignores.encode())
    assert not (tmp_path / "CLAUDE.md").exists()
    assert "BEGIN YOKE PACK" not in text.decode()[slice(*block_span(text.decode()))]
    # Repeating get has the existing named recovery and makes no changes.
    with pytest.raises(runner.PackClientError, match="already installed.*use update"):
        operation(tmp_path, apply=True)
    repeat = operation(tmp_path, action="update", apply=True)
    assert not repeat["plans"][0]["plan"]["changed"]
    assert (tmp_path / "AGENTS.md").read_bytes() == text
    guidance(tmp_path, "Refreshed Yoke rules", records)
    refreshed = (tmp_path / "AGENTS.md").read_bytes()
    assert custom.encode() in refreshed if existing else True
    assert refreshed.count(b"BEGIN YOKE PACK") == 1
    upgraded = copy.deepcopy(scaffold)
    upgraded["version"] = "1.1.4"
    for row in upgraded["files"]:
        if row["path"] == "AGENTS.md":
            row["content"] = row["content"].replace(
                "Application guidance", "Application references"
            )
            row["sha256"] = hashlib.sha256(row["content"].encode()).hexdigest()
        if row["path"] == ".gitignore":
            row["content"] = row["content"].replace("temp.txt", "scaffold-cache/")
            row["sha256"] = hashlib.sha256(row["content"].encode()).hexdigest()
    upgraded["content_digest"] = pack_catalog._content_digest(upgraded["files"])
    _validate_bundle(upgraded)
    monkeypatch.setattr(
        runner,
        "_fetch_bundle",
        lambda *a, version=None, **k: (
            scaffold if version == scaffold["version"] else upgraded
        ),
    )
    update_preview = operation(tmp_path, action="update")
    update = operation(tmp_path, action="update", apply=True)
    assert update["plans"] == update_preview["plans"]
    assert update["applied"]
    result = (tmp_path / "AGENTS.md").read_bytes()
    assert result == refreshed.replace(
        b"Application guidance", b"Application references"
    )
    assert "scaffold-cache/" in (tmp_path / ".gitignore").read_text()
    if existing:
        assert (tmp_path / ".gitignore").read_bytes().startswith(ignores.encode())
    receipt = load_receipt(tmp_path)["packs"][SLUG]
    assert receipt["version"] == upgraded["version"]
    entry = next(row for row in upgraded["files"] if row["path"] == "AGENTS.md")
    assert receipt["files"]["AGENTS.md"]["sha256"] == entry["sha256"]
    assert receipt["content_digest"] == upgraded["content_digest"]
    # Build the actual rendered consumer's Python sources, not template bytes.
    for source in (tmp_path / "app").rglob("*.py"):
        compile(source.read_bytes(), str(source), "exec")


def test_application_collision_refuses_entire_install_with_recovery(tmp_path, scaffold):
    existing = tmp_path / "app/api/main.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("print('custom application')\n")
    guidance(tmp_path)
    before = (tmp_path / "AGENTS.md").read_bytes()
    report = operation(tmp_path, apply=True)
    assert report["refused"]
    conflict = report["plans"][0]["plan"]["conflicts"][0]
    assert conflict["reason"] == "existing_project_file"
    assert "preview" in conflict["recovery"]
    assert (tmp_path / "AGENTS.md").read_bytes() == before
    assert not (tmp_path / ".yoke/packs.json").exists()


@pytest.mark.parametrize(
    "shape", ["missing_end", "duplicate", "reversed", "nested_yoke", "inline"]
)
def test_malformed_boundaries_refuse_without_writes(tmp_path, scaffold, shape):
    entry = next(row for row in scaffold["files"] if row["path"] == "AGENTS.md")
    content = entry["content"]
    begin, end = content.splitlines()[0], content.splitlines()[-1]
    invalid = {
        "missing_end": content.replace(end, ""),
        "duplicate": content + content,
        "reversed": end + "\n" + begin + "\n",
        "nested_yoke": render_block(content) + "\n",
        "inline": "project prefix " + content,
    }[shape]
    (tmp_path / "AGENTS.md").write_text(invalid)
    report = operation(tmp_path, apply=True)
    assert report["refused"]
    assert report["plans"][0]["plan"]["conflicts"][0]["recovery"]
    assert (tmp_path / "AGENTS.md").read_text() == invalid
    assert not (tmp_path / "app").exists()


def test_old_whole_file_baseline_updates_to_explicit_contributions(
    tmp_path, scaffold, monkeypatch
):
    old = runner._fetch_bundle("sample", SLUG, version="1.1.2")
    monkeypatch.setattr(runner, "_fetch_bundle", lambda *a, version=None, **k: old)
    assert operation(tmp_path, apply=True)["applied"]
    monkeypatch.setattr(
        runner,
        "_fetch_bundle",
        lambda *a, version=None, **k: old if version == old["version"] else scaffold,
    )
    assert operation(tmp_path, action="update", apply=True)["applied"]
    assert (tmp_path / "AGENTS.md").read_text().count("BEGIN YOKE PACK") == 1
    assert "Yoke Operating Layer" not in (tmp_path / "AGENTS.md").read_text()
    assert "BEGIN YOKE PACK" in (tmp_path / ".gitignore").read_text()


def test_customized_contribution_update_conflicts_and_cannot_be_bypassed(
    tmp_path, scaffold
):
    entry = next(row for row in scaffold["files"] if row["path"] == "AGENTS.md")
    (tmp_path / "AGENTS.md").write_text(
        entry["content"].replace("Application guidance", "Project custom guidance")
    )
    incoming = dict(
        entry,
        content=entry["content"].replace(
            "Application guidance", "New upstream guidance"
        ),
        sha256="changed",
    )
    plan = plan_update(tmp_path, [entry], [incoming])
    assert plan["conflicts"][0]["reason"] == "overlapping_contribution_customization"
    with pytest.raises(runner.PackClientError, match="cannot bypass"):
        runner._accept_current_conflicts(plan, ["AGENTS.md"])


def test_customized_old_guidance_has_reachable_manual_recovery(tmp_path, scaffold):
    old = runner._fetch_bundle("sample", SLUG, version="1.1.2")
    prior = next(row for row in old["files"] if row["path"] == "AGENTS.md")
    incoming = next(row for row in scaffold["files"] if row["path"] == "AGENTS.md")
    target = tmp_path / "AGENTS.md"
    target.write_text(
        prior["content"].replace("Think carefully", "Follow custom policy")
    )
    refusal = plan_update(tmp_path, [prior], [incoming])
    assert refusal["conflicts"][0]["reason"] == "whole_file_to_contribution_conflict"
    reconciled = (
        render_block("Yoke rules") + "\n# Custom policy\n" + incoming["content"]
    )
    target.write_text(reconciled)
    recovered = plan_update(tmp_path, [prior], [incoming])
    assert recovered["conflicts"] == []
    assert recovered["unchanged"] == ["AGENTS.md"]
    assert target.read_text() == reconciled


def test_only_explicit_bounded_files_compose(tmp_path, scaffold):
    source = next(row for row in scaffold["files"] if row["path"] == "AGENTS.md")
    for path in ("app.py", "docs/AGENTS.md", "CLAUDE.md"):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("project content\n")
        plan = plan_get(tmp_path, [dict(source, path=path)])
        assert plan["conflicts"][0]["reason"] == "existing_project_file"


def test_bundle_refuses_malformed_or_foreign_contribution_source(scaffold):
    bad = copy.deepcopy(scaffold)
    entry = next(row for row in bad["files"] if row["path"] == "AGENTS.md")
    entry["content"] = entry["content"].replace(SLUG, SLUG + "-other")
    entry["sha256"] = hashlib.sha256(entry["content"].encode()).hexdigest()
    bad["content_digest"] = pack_catalog._content_digest(bad["files"])
    with pytest.raises(runner.PackClientError, match="owner_mismatch"):
        _validate_bundle(bad)
    entry["content"] = entry["content"].split("<!-- END")[0]
    entry["sha256"] = hashlib.sha256(entry["content"].encode()).hexdigest()
    with pytest.raises(runner.PackClientError, match="malformed_pack_contribution"):
        _validate_bundle(bad)


def test_contributions_cannot_be_relinked_to_noncanonical_paths(
    tmp_path, scaffold, monkeypatch
):
    assert operation(tmp_path, apply=True)["applied"]
    (tmp_path / "AGENTS.md").rename(tmp_path / "moved.md")
    monkeypatch.setattr(relink, "_fetch_bundle", lambda *a, **k: scaffold)
    monkeypatch.setattr(relink, "_assert_checkout_project", lambda *a: None)
    with pytest.raises(runner.PackClientError, match="target_fixed"):
        relink.run_pack_relink(
            tmp_path,
            project="sample",
            pack=SLUG,
            from_path="AGENTS.md",
            to_path="moved.md",
            apply=True,
        )
    assert (
        load_receipt(tmp_path)["packs"][SLUG]["files"]["AGENTS.md"]["path"]
        == "AGENTS.md"
    )
