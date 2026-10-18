"""Public publication failures and recursive contributor review stay distinct."""

from pathlib import Path
import shutil
import subprocess

from yoke_core.domain.documentation_navigation import iter_nodes, load_navigation
from yoke_core.domain.documentation_render import render_page
from yoke_core.domain.install_bundle_tree_sync import PACKAGED_TREE_REL
from yoke_project_checks import check_docs


class Collector:
    def record(self, identifier, title, result, detail):
        self.result, self.detail = result, detail


def _seed(root):
    source = root / "docs/public"
    fixtures = Path(__file__).parents[1] / "domain/fixtures/documentation_corpus"
    shutil.copytree(fixtures, source)
    tree = load_navigation(source)
    for node in iter_nodes(tree):
        path = source / node.path
        path.write_text(render_page(tree, node, path.read_text()))
    for mirror in (root / ".yoke/docs", root / PACKAGED_TREE_REL / "docs/public"):
        shutil.copytree(source, mirror)
    (root / "README.md").write_text("# Source\n")
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    (root / "runtime/harness").mkdir(parents=True)
    (root / "runtime/harness/marker").write_text("source fixture")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)


def _run(root, monkeypatch):
    monkeypatch.setattr(check_docs._base, "_resolve_repo_root", lambda: str(root))
    collector = Collector()
    check_docs.hc_doc_health(None, None, collector)
    return collector


def test_complete_corpus_passes(tmp_path, monkeypatch):
    _seed(tmp_path)
    assert _run(tmp_path, monkeypatch).result == "PASS"


def test_nested_contributor_fragments_warn_and_archives_are_excluded(
    tmp_path, monkeypatch
):
    _seed(tmp_path)
    nested = tmp_path / "docs/contributor/deep"
    nested.mkdir(parents=True)
    (nested / "guide.md").write_text("# Guide\n[Absent](#absent)\n")
    archive = tmp_path / "docs/archive"
    archive.mkdir()
    (archive / "history.md").write_text("[History](absent.md)\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "docs"], check=True)
    result = _run(tmp_path, monkeypatch)
    assert result.result == "WARN"
    assert "REVIEW LINK_FRAGMENT_MISSING" in result.detail
    assert "Repair:" in result.detail
    assert "history.md" not in result.detail


def test_public_links_and_stale_copies_fail(tmp_path, monkeypatch):
    _seed(tmp_path)
    path = tmp_path / "docs/public/guide/setup.md"
    path.write_text(path.read_text() + "\n[Absent](#absent)\n")
    result = _run(tmp_path, monkeypatch)
    assert result.result == "FAIL"
    assert "LINK_FRAGMENT_MISSING" in result.detail
    assert "STALE_GENERATED_COPY" in result.detail
    assert "Repair:" in result.detail


def test_retired_reference_in_tracked_consumer_fails(tmp_path, monkeypatch):
    _seed(tmp_path)
    path = tmp_path / "consumer.txt"
    path.write_text(".yoke/" + "docs/" + "reference/retired.md\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "consumer.txt"], check=True)
    result = _run(tmp_path, monkeypatch)
    assert result.result == "FAIL"
    assert "RETIRED_REFERENCE consumer.txt:1" in result.detail


def test_missing_public_tree_cannot_downgrade_a_source_checkout(tmp_path, monkeypatch):
    _seed(tmp_path)
    shutil.rmtree(tmp_path / "docs/public")
    result = _run(tmp_path, monkeypatch)
    assert result.result == "FAIL"
    assert "NAV_SCHEMA nav.yaml" in result.detail


def test_gitless_generic_docs_keep_recursive_link_health(tmp_path, monkeypatch, capsys):
    (tmp_path / "README.md").write_text("# Repository\n")
    docs = tmp_path / "docs/nested"
    docs.mkdir(parents=True)
    (docs / "guide.md").write_text("[Present](target.md)\n")
    (docs / "target.md").write_text("# Target\n")
    assert _run(tmp_path, monkeypatch).result == "PASS"
    progress = capsys.readouterr().out
    assert "running HC-doc-health check-readme" in progress
    assert "running HC-doc-health scan-doc-links 0/2" in progress
    (docs / "guide.md").write_text("[Missing](missing.md)\n")
    result = _run(tmp_path, monkeypatch)
    assert result.result == "FAIL"
    assert "LINK_TARGET_MISSING" in result.detail
    assert "broken link" in result.detail
    assert "Repair:" in result.detail
