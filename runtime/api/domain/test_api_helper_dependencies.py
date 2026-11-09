"""Domain helper imports must stay below the API composition layer."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from yoke_core.domain import repo_root


def test_domain_invariants_do_not_import_api_modules() -> None:
    domain = Path(repo_root.__file__).parent
    forbidden = []
    for path in sorted(domain.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            forbidden.extend(
                f"{path.name}:{node.lineno}: {name}"
                for name in names
                if name == "yoke_core.api" or name.startswith("yoke_core.api.")
            )
    assert forbidden == []


@pytest.mark.parametrize(
    ("module", "symbol", "owner"),
    [
        ("repo_root", "find_repo_root", "yoke_core.domain.repo_root"),
        ("observability", "trace_context", "yoke_core.domain.observability"),
        ("oidc_config", "resolve_oidc_config", "yoke_core.domain.oidc_config"),
        ("oidc_client", "discover", "yoke_core.domain.oidc_client"),
        ("oidc_flow_state", "FlowState", "yoke_core.domain.oidc_flow_state"),
        ("oidc_stub_provider", "StubOidcProvider", "yoke_core.domain.oidc_stub_provider"),
        (
            "health_payload_contract",
            "migration_readiness_problem",
            "yoke_contracts.health_payload_contract",
        ),
    ],
)
def test_api_import_surface_shares_the_lower_layer_owner(module, symbol, owner) -> None:
    api = importlib.import_module(f"yoke_core.api.{module}")
    implementation = importlib.import_module(owner)
    assert getattr(api, symbol) is getattr(implementation, symbol)
