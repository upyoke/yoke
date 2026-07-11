"""Declarative database security-group peer adoption coverage."""

from __future__ import annotations

import ast
import types
from pathlib import Path

from runtime.api.domain.test_webapp_database_stack_rotation import (
    _load_database_stack_module,
)


def _template_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "templates"
        / "webapp"
        / "infra"
        / "webapp_database_stack.py"
    )


def test_database_security_group_ingress_uses_per_peer_rule_builder():
    tree = ast.parse(_template_path().read_text(encoding="utf-8"))
    security_group = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "SecurityGroup"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "databaseSecurityGroup"
    )
    ingress = next(
        keyword.value for keyword in security_group.keywords if keyword.arg == "ingress"
    )

    assert ast.unparse(ingress) == (
        "_database_ingress_rules(args.allowed_security_group_ids)"
    )


def test_ingress_builder_emits_one_stable_rule_per_unique_peer(monkeypatch):
    module = _load_database_stack_module(monkeypatch)

    class _IngressArgs:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.aws.ec2 = types.SimpleNamespace(
        SecurityGroupIngressArgs=_IngressArgs,
    )

    rules = module._database_ingress_rules(
        [
            "sg-06796881065d2cbcc",
            "sg-04b29aba823f5fae5",
            "sg-06796881065d2cbcc",
        ]
    )

    assert [rule.kwargs["security_groups"] for rule in rules] == [
        ["sg-04b29aba823f5fae5"],
        ["sg-06796881065d2cbcc"],
    ]
    assert module._DATABASE_INGRESS_DESCRIPTION == (
        "PostgreSQL from caller-provided origin security groups"
    )
    assert all(
        rule.kwargs["description"]
        == "PostgreSQL from caller-provided origin security groups"
        for rule in rules
    )
    assert all(rule.kwargs["protocol"] == "tcp" for rule in rules)
    assert all(rule.kwargs["from_port"] == 5432 for rule in rules)
    assert all(rule.kwargs["to_port"] == 5432 for rule in rules)


def test_deduplication_preserves_output_like_peer_before_sorted_strings(monkeypatch):
    module = _load_database_stack_module(monkeypatch)
    origin_output = types.SimpleNamespace(value="sg-origin-output")

    peers = module._deduplicated_security_group_ids(
        [
            origin_output,
            "sg-external-b",
            "sg-external-a",
            origin_output,
            "sg-external-b",
        ]
    )

    assert peers[0] is origin_output
    assert peers[1:] == ["sg-external-a", "sg-external-b"]
