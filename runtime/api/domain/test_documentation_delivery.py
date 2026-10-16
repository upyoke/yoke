"""Publication refuses incomplete teaching and identity without mutating it."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from yoke_core.domain import documentation_navigation as nav
from yoke_core.domain.documentation_render import render_page
from yoke_core.domain.documentation_residue import scan_retired_references
from yoke_core.domain import install_bundle_docs_validation as validation
from yoke_core.domain.install_bundle import InstallBundleError, validate_docs_for_bundle
from yoke_core.domain.install_bundle_tree_sync import PACKAGED_TREE_REL

FIXTURES = Path(__file__).parent / "fixtures/documentation_corpus"


def _corpus(root):
    shutil.copytree(FIXTURES, root, dirs_exist_ok=True)
    tree = nav.load_navigation(root)
    for node in nav.iter_nodes(tree):
        path = root / node.path
        path.write_text(render_page(tree, node, path.read_text()))
    return root


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "source"
    source = _corpus(root / "docs/public")
    for target in (root / ".yoke/docs", root / PACKAGED_TREE_REL / "docs/public"):
        shutil.copytree(source, target)
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    (root / "runtime/harness").mkdir(parents=True)
    (root / "runtime/harness/marker").write_text("source fixture")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.name=Example",
        "-c",
        "user.email=example@example.test",
        "commit",
        "-qm",
        "Create source corpus",
    )
    commit = _git(root, "rev-parse", "HEAD")
    proof = tmp_path / "yoke-docs-build-evidence.json"
    proof.write_text(
        json.dumps(
            dict(
                consumer="example-docs",
                source_commit=commit,
                built_at="2026-10-16T12:00:00Z",
            )
        )
    )
    return root, commit, proof


def test_complete_snapshot_and_tracked_source(candidate, tmp_path):
    root, _, _ = candidate
    assert validation.validate_public_corpus(root / "docs/public") == []
    snapshot = _corpus(tmp_path / "snapshot")
    assert validation.validate_public_corpus(snapshot) == []
    (snapshot / "unlisted.md").write_text("# Unlisted\n")
    assert "UNLISTED_PAGE" in {
        r.code for r in validation.validate_public_corpus(snapshot)
    }


@pytest.mark.parametrize(
    "text,code",
    [
        ("line\n" * 351, "OVERSIZED_PAGE"),
        ("[Absent](absent.md)\n", "LINK_TARGET_MISSING"),
        ("[Heading](guide/setup.md#absent)\n", "LINK_FRAGMENT_MISSING"),
        ("personal /" + "Users/alice/private/capture.png\n", "PRIVATE_CONTENT"),
        ("machine_id: " + "ab12cd34-ef56-7890-ab12-cd34ef567890\n", "PRIVATE_CONTENT"),
    ],
)
def test_public_refusal_identifies_target_and_repair(tmp_path, text, code):
    root = _corpus(tmp_path)
    path = root / "index.md"
    path.write_text(path.read_text() + "\n" + text)
    refusals = validation.validate_public_corpus(root)
    assert code in {r.code for r in refusals}
    assert all(r.target and r.detail and r.repair for r in refusals)


def test_advisory_and_portable_examples_do_not_refuse(tmp_path):
    root = _corpus(tmp_path)
    path = root / "index.md"
    path.write_text(
        path.read_text()
        + "\n"
        + "a" * 20_001
        + "\n"
        + "Scratch /tmp/example.txt; home /"
        + "Users/me/.local/bin/yoke\n"
        + "machine_id: 00000000-0000-0000-0000-000000000001\n"
        + "Example machine_id: ab12cd34-ef56-7890-ab12-cd34ef567890\n"
    )
    assert validation.validate_public_corpus(root) == []


def test_stale_derived_blocks_and_copies_are_inspected(candidate):
    root, _, _ = candidate
    assert validation.validate_published_copies(root) == []
    copy = root / ".yoke/docs/guide/setup.md"
    copy.write_text(copy.read_text() + "\n" + "line\n" * 351)
    codes = {r.code for r in validation.validate_published_copies(root)}
    assert codes == {"STALE_GENERATED_COPY", "OVERSIZED_PAGE"}
    page = root / "docs/public/guide/setup.md"
    page.write_text("# Setup\n")
    assert "STALE_NAV_BLOCK" in {
        r.code for r in validation.validate_public_corpus(page.parents[1])
    }


def test_valid_identity_and_cli(candidate, capsys):
    root, commit, proof = candidate
    assert validation.verify_candidate(root, commit, consumer_evidence=proof) == []
    assert (
        validation.main(
            [
                "verify-candidate",
                "--root",
                str(root),
                "--commit",
                commit,
                "--consumer-evidence",
                str(proof),
            ]
        )
        == 0
    )
    assert "PASS" in capsys.readouterr().out


@pytest.mark.parametrize(
    "kind",
    [
        "short",
        "unresolvable",
        "other-head",
        "dirty",
        "other-dirty",
        "receipt",
        "packaged",
        "extra-copy",
    ],
)
def test_candidate_mismatch(candidate, kind, tmp_path):
    root, commit, proof = candidate
    receipt = None
    if kind == "short":
        commit = commit[:12]
    elif kind == "unresolvable":
        commit = "f" * 40
    elif kind == "other-head":
        _git(
            root,
            "-c",
            "user.name=Example",
            "-c",
            "user.email=example@example.test",
            "commit",
            "--allow-empty",
            "-qm",
            "Change candidate",
        )
    elif kind == "dirty":
        (root / "docs/public/index.md").write_text("# Dirty\n")
    elif kind == "other-dirty":
        (root / "new-source.py").write_text("uncommitted source change")
    elif kind == "receipt":
        receipt = tmp_path / "receipt.json"
        receipt.write_text(json.dumps(dict(source_build="a" * 40)))
    else:
        path = (
            root / PACKAGED_TREE_REL / "docs/public/index.md"
            if kind == "packaged"
            else root / ".yoke/docs/extra.md"
        )
        path.write_text("wrong candidate\n")
    refusals = validation.verify_candidate(
        root, commit, receipt=receipt, consumer_evidence=proof
    )
    identity = [r for r in refusals if r.code == "CANDIDATE_IDENTITY_MISMATCH"]
    assert identity
    if kind in {"dirty", "other-dirty"}:
        expected = "docs/public/index.md" if kind == "dirty" else "new-source.py"
        assert any(expected in r.target for r in identity)
        assert (
            identity[0].repair
            == "commit or discard the listed changes and rebuild from the declared full candidate commit"
        )
    else:
        assert any(
            r.repair == "rebuild from the declared full candidate commit"
            for r in identity
        )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "unreadable",
        "invalid-json",
        [],
        {},
        dict(consumer="docs", source_commit="short", built_at="2026-10-16T12:00:00Z"),
        dict(consumer="docs", source_commit="f" * 40, built_at="2026-10-16T12:00:00Z"),
        dict(consumer="docs", source_commit="MATCH", built_at="not-an-instant"),
        dict(consumer="docs", source_commit="MATCH", built_at="2026-02-31T12:00:00Z"),
        dict(consumer=4, source_commit="MATCH", built_at="2026-10-16T12:00:00Z"),
        dict(
            consumer="docs",
            source_commit="MATCH",
            built_at="2026-10-16T12:00:00Z",
            extra="unknown",
        ),
    ],
)
def test_consumer_proof_contract(candidate, value):
    root, commit, proof = candidate
    if value is None:
        proof = None
    elif value == "unreadable":
        proof.unlink()
    elif value == "invalid-json":
        proof.write_text("{")
    else:
        proof.write_text(json.dumps(value).replace("MATCH", commit))
    refusals = validation.verify_candidate(root, commit, consumer_evidence=proof)
    assert [r.code for r in refusals] == ["CONSUMER_PROOF_MISSING"]
    assert (
        refusals[0].repair
        == "rebuild the consumer from the declared full commit and supply its evidence"
    )


def test_repairs_match_the_shipped_producer_contract():
    contract = (
        Path(__file__).parents[3] / "docs/public/documentation/navigation.md"
    ).read_text()
    normalized = " ".join(contract.split())
    assert validation._IDENTITY_REPAIR in normalized
    assert validation._PROOF_REPAIR in normalized


def test_publication_cache_tracks_content_and_refuses_gitless_changes(tmp_path):
    source = _corpus(tmp_path / "docs/public")
    validate_docs_for_bundle(tmp_path)
    (source / "index.md").write_text("# Root\n\n[Absent](absent.md)\n")
    before = (source / "index.md").read_bytes()
    with pytest.raises(InstallBundleError, match="LINK_TARGET_MISSING"):
        validate_docs_for_bundle(tmp_path)
    assert (source / "index.md").read_bytes() == before


def test_retired_scan_false_positives_and_anchored_matches(candidate):
    root, _, _ = candidate
    fixtures = {
        "docs/qa-platform/cli-reference.md": "# Live contributor\n",
        "examples.txt": "workflows/index.md start/install.md verification/index.md docs/qa-platform/cli-reference.md\n",
        ".test_durations": "docs/" + "public/" + "reference/old.md\n",
        "docs/archive/history.md": ".yoke/" + "docs/" + "guides/old.md\n",
        "packs/example/versions/1.0.0/frozen.md": "docs/"
        + "public/"
        + "reference/old.md\n",
        str(PACKAGED_TREE_REL / "packs/example/versions/1.0.0/frozen.md"): "docs/"
        + "public/"
        + "reference/old.md\n",
    }
    for rel, text in fixtures.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(root, "add", "-A")
    assert scan_retired_references(root) == []
    (root / "examples.txt").write_text(
        "docs/" + "public/" + "reference/x.md\n.yoke/" + "docs/" + "guides/x.md\n"
    )
    (root / "docs/public/guide/setup.md").write_text(
        "# Setup\n[Retired](../install.md)\n"
    )
    assert len(scan_retired_references(root)) == 3
    (root / "docs/public/nav.yaml").write_text("sections:\n  pages: []\n")
    assert len(scan_retired_references(root)) == 5
