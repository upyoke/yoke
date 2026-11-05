"""The published corpus contract controls producer validation."""

import json

import pytest

from yoke_contracts.project_contract.docs_corpus_files import CorpusRefusal, refuse_unexpected_file
from yoke_core.domain import docs_corpus_rule as contract
from yoke_core.domain import install_bundle_docs_validation as validation


@pytest.mark.parametrize("name", [
    "index.md", "guide/setup.md", "nav.yaml", "assets/site.css",
    "assets/nested/diagram.svg", "assets/demo.html", "materialization.json",
    "yoke-docs-build-evidence.json",
])
def test_published_rule_accepts_supported_files(name):
    rule = contract.load_corpus_rule()
    assert not isinstance(rule, CorpusRefusal)
    assert refuse_unexpected_file(name, rule) == []


@pytest.mark.parametrize("name,symlink", [
    ("extra.txt", False), ("extra.woff2", False), ("index.md", True),
    ("nested/materialization.json", False), ("assets/site.css.bak", False),
])
def test_published_rule_refuses_unsupported_files(name, symlink):
    rule = contract.load_corpus_rule()
    assert not isinstance(rule, CorpusRefusal)
    refusal, = refuse_unexpected_file(name, rule, symlink=symlink)
    assert refusal.code == "DOCS_CORPUS_UNEXPECTED_FILE"
    assert refusal.repair == "remove it from docs/public"


@pytest.mark.parametrize("contents", [
    None, "{", "[]", "{}", '"text"',
    json.dumps({"schemaVersion": True, "allowedPathPattern": ".*", "identityFiles": ["x"]}),
    json.dumps({"schemaVersion": 2, "allowedPathPattern": ".*", "identityFiles": ["x"]}),
    json.dumps({"schemaVersion": 1, "allowedPathPattern": "[", "identityFiles": ["x"]}),
    json.dumps({"schemaVersion": 1, "allowedPathPattern": ".*", "identityFiles": [{}]}),
    json.dumps({"schemaVersion": 1, "allowedPathPattern": ".*", "identityFiles": ["a/b"]}),
])
def test_unavailable_contract_refuses_with_repair(tmp_path, monkeypatch, contents):
    path = tmp_path / "docs-corpus-files.json"
    if contents is not None:
        path.write_text(contents)
    monkeypatch.setattr(contract, "CONTRACT_PATH", path)
    refusal, = validation.validate_public_corpus(tmp_path)
    assert refusal.code == "DOCS_CORPUS_RULE_MISSING"
    assert refusal.target == str(path)
    assert "restore" in refusal.repair


def test_contract_changes_control_validation(tmp_path, monkeypatch):
    path = tmp_path / "docs-corpus-files.json"
    path.write_text(json.dumps({
        "schemaVersion": 1, "allowedPathPattern": r"docs/.*\.md",
        "identityFiles": ["identity.json"],
    }))
    monkeypatch.setattr(contract, "CONTRACT_PATH", path)
    rule = contract.load_corpus_rule()
    assert not isinstance(rule, CorpusRefusal)
    assert not refuse_unexpected_file("docs/start.md", rule)
    assert not refuse_unexpected_file("identity.json", rule)
    assert refuse_unexpected_file("index.md", rule)
    assert refuse_unexpected_file("identityXjson", rule)
