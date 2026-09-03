"""The container image's source-tree bootstrap resolves every import it makes.

The builder stage runs one module straight from the source tree, before any
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
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]

#: The image builds at /build; every declared path is repo-relative under it.
_IMAGE_BUILD_ROOT = "/build/"

#: Packages the source tree owns. Everything else is a third-party or stdlib
#: import the wheel install resolves, not something PYTHONPATH must cover.
_FIRST_PARTY_PREFIX = "yoke_"

#: The builder's `RUN PYTHONPATH=<roots> ... runpy.run_path('<module>')` step.
_BOOTSTRAP_STEP = re.compile(
    r"RUN PYTHONPATH=(?P<roots>\S+)"
    r"[\s\S]*?runpy\.run_path\('(?P<module>[^']+)'\)"
)


def _repo_path(declared: str) -> Path:
    return REPO_ROOT / declared.removeprefix(_IMAGE_BUILD_ROOT)


def _parse_bootstrap_step() -> tuple[list[Path], Path]:
    """Return the bootstrap's PYTHONPATH roots and entry module as repo paths."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    step = _BOOTSTRAP_STEP.search(dockerfile)
    assert step is not None, (
        "Dockerfile no longer runs a source-tree bootstrap through "
        "runpy.run_path with an explicit PYTHONPATH. Update this guard to "
        "match the new shape rather than deleting it -- the failure it "
        "catches is an unresolvable import inside the image build."
    )
    roots = [_repo_path(entry) for entry in step.group("roots").split(":")]
    return roots, _repo_path(step.group("module"))


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
        "RUN PYTHONPATH= list in the Dockerfile builder stage."
    )


def test_dockerfile_bootstrap_imports_before_dependencies_install() -> None:
    roots, entry = _parse_bootstrap_step()
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

    assert completed.returncode == 0, completed.stderr
