"""Domain helpers remain independent of registered service handlers."""

import ast
from pathlib import Path


def test_domain_does_not_import_handler_modules():
    root = Path(__file__).resolve().parents[3]
    domain = root / "packages/yoke-core/src/yoke_core/domain"
    violations = []
    for path in sorted(domain.rglob("*.py")):
        if "handlers" in path.relative_to(domain).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
            if any(
                name == "yoke_core.domain.handlers"
                or name.startswith("yoke_core.domain.handlers.")
                for name in modules
            ):
                violations.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not violations, "Move shared logic into domain: " + ", ".join(violations)
