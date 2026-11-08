"""The container image's source-tree bootstrap resolves every import it makes.

The runtime base runs one module straight from the source tree, before any
wheel exists, so the interpreter resolves its imports from the ``PYTHONPATH``
the Dockerfile spells out and nothing else. That list is written by hand and
has no other reader, so an import added to a bootstrapped module can leave it
behind silently -- and the first report is a failed image build, several
minutes into CI, naming a module rather than the path that omits it.

This walks the bootstrap entry module's first-party imports transitively and
resolves each one against exactly the roots the Dockerfile declares, so the
omission fails here, in seconds, naming the package and the fix.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

#: Packages the source tree owns; other imports come from Python/dependencies.
_FIRST_PARTY_PREFIX = "yoke_"

_BOOTSTRAP_STEP = re.compile(
    r"^RUN [^\n]*PYTHONPATH=(?P<roots>\S+)"
    r"[^\n]*runpy\.run_path\('(?P<module>[^']+)'\)",
    re.M,
)


def _bootstrap_inputs() -> tuple[list[str], str, dict[str, Path]]:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text().replace("\\\n", " ")
    step = _BOOTSTRAP_STEP.search(dockerfile)
    assert step is not None, (
        "Dockerfile no longer runs a source-tree bootstrap through "
        "runpy.run_path with an explicit PYTHONPATH. Update this guard to "
        "match the new shape rather than deleting the isolated import check."
    )
    mounts = {
        target: REPO_ROOT / source
        for source, target in re.findall(
            r"--mount=type=bind,source=([^, ]+),target=([^, ]+)", step.group()
        )
    }
    assert mounts, "bootstrap must declare its source bind mounts"
    return step.group("roots").split(":"), step.group("module"), mounts


def _repo_path(declared: str, mounts: dict[str, Path]) -> Path:
    for target, source in sorted(mounts.items(), key=lambda entry: -len(entry[0])):
        if declared == target:
            return source
        if declared.startswith(target + "/"):
            return source / declared.removeprefix(target + "/")
        if target.startswith(declared + "/"):
            root = source
            for _part in Path(target).relative_to(declared).parts:
                root = root.parent
            return root
    raise AssertionError(f"bootstrap path {declared} has no declared source mount")


def _parse_bootstrap_step() -> tuple[list[Path], Path]:
    roots, entry, mounts = _bootstrap_inputs()
    return [_repo_path(root, mounts) for root in roots], _repo_path(entry, mounts)


def _resolve(module_name: str, roots: list[Path]) -> Path | None:
    """Resolve a dotted module name to its file under one of `roots`."""
    parts = module_name.split(".")
    for root in roots:
        base = root.joinpath(*parts)
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate.is_file():
                return candidate
    return None


def _imported_names(tree: ast.AST) -> set[str]:
    """Every first-party dotted module name the parsed source imports."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.name
                for alias in node.names
                if alias.name.startswith(_FIRST_PARTY_PREFIX)
            )
        elif isinstance(node, ast.ImportFrom):
            # `level` marks a relative import; the bootstrap tree uses absolute
            # imports, and a relative one resolves within its own package
            # anyway, so it can never reach a root the list omits.
            if node.level or not (node.module or "").startswith(_FIRST_PARTY_PREFIX):
                continue
            module = node.module or ""
            names.add(module)
            # `from pkg import submodule` imports a module, not an attribute;
            # only the resolvable ones are kept, so real attributes drop out.
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def _unresolvable_imports(entry: Path, roots: list[Path]) -> dict[str, str]:
    """Map each unresolvable first-party import to the module that imports it."""
    missing: dict[str, str] = {}
    seen: set[Path] = set()
    queue = [entry]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        tree = ast.parse(current.read_text(encoding="utf-8"), filename=str(current))
        for name in sorted(_imported_names(tree)):
            resolved = _resolve(name, roots)
            if resolved is not None:
                queue.append(resolved)
                continue
            # A `from pkg import thing` attribute is not a module; only a
            # top-level package that resolves nowhere is a real omission.
            if _resolve(name.split(".")[0], roots) is None:
                missing[name] = str(current.relative_to(REPO_ROOT))
    return missing


def test_dockerfile_bootstrap_pythonpath_roots_exist() -> None:
    roots, entry = _parse_bootstrap_step()

    assert roots, "the bootstrap step declares no PYTHONPATH roots"
    for root in roots:
        assert root.is_dir(), (
            f"Dockerfile bootstrap PYTHONPATH names {root}, which is not a "
            "directory in this checkout"
        )
    assert entry.is_file(), f"bootstrap entry module {entry} does not exist"


def test_dockerfile_bootstrap_pythonpath_resolves_core_imports() -> None:
    roots, entry = _parse_bootstrap_step()

    missing = _unresolvable_imports(entry, roots)

    assert not missing, (
        "the container's source-tree bootstrap imports packages its "
        "PYTHONPATH does not cover, so the image build fails with "
        "ModuleNotFoundError: "
        + ", ".join(
            f"{name} (imported by {importer})"
            for name, importer in sorted(missing.items())
        )
        + ". Add the owning packages/yoke-*/src directory to the "
        "bootstrap PYTHONPATH and source mounts in the Dockerfile."
    )


@pytest.mark.parametrize("omit_contracts", [False, True])
def test_bootstrap_imports_from_only_declared_mounts(tmp_path, omit_contracts) -> None:
    roots, entry, mounts = _bootstrap_inputs()
    # Materialize only mounted files, never the whole checkout or installed
    # workspace. A missing contracts mount must fail the same isolated import.
    for destination, source in mounts.items():
        if omit_contracts and destination.startswith("/bootstrap/contracts/"):
            continue
        target = tmp_path / destination.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    roots = [tmp_path / root.lstrip("/") for root in roots]
    entry = tmp_path / entry.lstrip("/")
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(str(root) for root in roots),
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            f"import runpy; runpy.run_path({str(entry)!r})",
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    if omit_contracts:
        assert completed.returncode != 0
        assert "yoke_contracts" in completed.stderr
    else:
        assert completed.returncode == 0, completed.stderr
