"""Collect native Windows smoke modules without importing unrelated OS tests."""

import ast
from pathlib import Path


def pytest_ignore_collect(collection_path: Path, config):
    """The smoke contract declares markers directly as pytest.mark.windows.

    Pytest's normal marker filtering happens after imports. Avoid importing
    unmarked Unix-only modules during this explicitly selected smoke suite;
    pytest still owns per-test selection and errors in selected modules.
    """
    if config.option.markexpr != "windows" or collection_path.suffix != ".py":
        return None
    if not collection_path.name.startswith("test_"):
        return None
    source = collection_path.read_bytes()
    if b"windows" not in source:
        return True
    tree = ast.parse(source, filename=str(collection_path))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "windows"
                and isinstance(node.value, ast.Attribute) and node.value.attr == "mark"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "pytest"):
            return None
    return True
