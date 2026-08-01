"""Discover a project's own health checks from its ``.yoke/doctor/`` folder.

A project keeps the checks that encode its own conventions next to its code
rather than in the shared engine. The folder is discovered the way pytest
discovers tests: every ``check_*.py`` file in ``<checkout>/.yoke/doctor/`` is
imported, and each ``hc_*`` function it defines becomes a health check with
the same declaration and reporting contract as an engine check.

A module states its checks one of two ways:

* explicitly, through a module-level ``PROJECT_HEALTH_CHECKS`` list of
  :class:`~yoke_core.engines.doctor_registry_types.HealthCheck` rows, which
  gives full control over slug, display name, and applicability. The name is
  deliberately distinct from the engine's own ``HEALTH_CHECKS``: a check
  module that imports the engine roster to inspect it must not thereby
  declare all of it as its own; or
* by convention, by defining ``hc_<name>(conn, args, rec)`` functions. The
  slug comes from the function name, the display name from the first line of
  its docstring, and the applicability from a module-level ``APPLICABILITY``
  default (or the universal shape).

Discovery only ever runs where the checkout exists, so a control-plane
server never imports project code. Import failures are surfaced as a FAIL
result, never swallowed: a project check that cannot load is a finding.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from yoke_core.engines.doctor_applicability import CheckApplicability, UNIVERSAL
from yoke_core.engines.doctor_registry_types import HealthCheck

#: Folder inside a project's ``.yoke/`` tree holding its own checks.
PROJECT_CHECKS_DIR = Path(".yoke") / "doctor"

#: Only files matching this pattern are imported, so the folder can also hold
#: helper modules, fixtures, and a README without them being collected.
CHECK_FILE_GLOB = "check_*.py"

#: Prefix marking a collected check function inside a discovered module.
CHECK_FUNCTION_PREFIX = "hc_"

#: Module-level name a check module uses to declare its rows explicitly.
#: Distinct from the engine's ``HEALTH_CHECKS`` so that importing the engine
#: roster — to inspect it, as a self-project check legitimately might — never
#: re-declares the whole thing as this project's own.
PROJECT_CHECKS_ATTRIBUTE = "PROJECT_HEALTH_CHECKS"

#: Package namespace discovered check modules are imported under. A check
#: module imports a sibling through it, so a folder of checks can share
#: helpers the way an engine package would.
PROJECT_CHECKS_PACKAGE = "yoke_project_checks"

_MODULE_NAMESPACE = PROJECT_CHECKS_PACKAGE


@dataclass(frozen=True)
class DiscoveryFailure:
    """One ``check_*.py`` file that could not be imported."""

    path: Path
    error: str


@dataclass(frozen=True)
class Discovery:
    """Everything one ``.yoke/doctor/`` folder yielded."""

    checks: List[HealthCheck]
    failures: List[DiscoveryFailure]


def project_checks_dir(checkout: Path) -> Path:
    """The ``.yoke/doctor/`` folder for *checkout*."""
    return Path(checkout) / PROJECT_CHECKS_DIR


def discover_project_checks(checkout: Optional[Path]) -> Discovery:
    """Collect the project-local checks declared under *checkout*."""
    if checkout is None:
        return Discovery(checks=[], failures=[])
    folder = project_checks_dir(checkout)
    if not folder.is_dir():
        return Discovery(checks=[], failures=[])
    register_project_checks_package(folder)
    checks: List[HealthCheck] = []
    failures: List[DiscoveryFailure] = []
    for path in sorted(folder.glob(CHECK_FILE_GLOB)):
        try:
            module = _import_check_module(path)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            failures.append(DiscoveryFailure(path=path, error=f"{exc}"))
            continue
        try:
            checks.extend(_collect(module))
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            failures.append(DiscoveryFailure(path=path, error=f"{exc}"))
    return Discovery(checks=checks, failures=failures)


def load_check_module(folder: Path, stem: str):
    """Import one module from a project's check folder by file stem.

    Public because a project's own tests need the same import path its
    checks run under. The folder is registered as the
    :data:`PROJECT_CHECKS_PACKAGE` package first, so a check module can
    import a sibling — ``from yoke_project_checks.check_x import helper`` —
    the way it did when both lived in the engine package.
    """
    register_project_checks_package(Path(folder))
    return _import_check_module(Path(folder) / f"{stem}.py")


def register_project_checks_package(folder: Path) -> None:
    """Make *folder* resolvable under the project-checks package namespace.

    Additive: one process may inspect several folders — a repo's own checks
    plus a fixture tree in a test — and registering the second must not make
    the first unimportable.
    """
    package = sys.modules.get(_MODULE_NAMESPACE)
    if package is None:
        package = importlib.util.module_from_spec(
            importlib.machinery.ModuleSpec(
                _MODULE_NAMESPACE, None, is_package=True,
            )
        )
        package.__path__ = []
        sys.modules[_MODULE_NAMESPACE] = package
    entry = str(folder)
    if entry not in package.__path__:
        package.__path__.insert(0, entry)


def _import_check_module(path: Path):
    """Import one check module, reusing any prior import of the same file.

    Re-executing on every discovery mints a fresh module object each time,
    so anything holding a reference to the previous one — a test that
    patched a helper, a paginating run between chunks — silently ends up
    looking at a module that is no longer the one in play. One file means
    one module object, however it was first imported.
    """
    module_name = f"{_MODULE_NAMESPACE}.{path.stem}"
    cached = sys.modules.get(module_name)
    if cached is not None and _is_same_file(getattr(cached, "__file__", None), path):
        return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load a module spec from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _is_same_file(candidate, path: Path) -> bool:
    if not candidate:
        return False
    try:
        return Path(candidate).resolve() == path.resolve()
    except OSError:  # pragma: no cover - unresolvable path is a miss
        return False


def _collect(module) -> List[HealthCheck]:
    declared = getattr(module, PROJECT_CHECKS_ATTRIBUTE, None)
    if declared is not None:
        rows = list(declared)
        bad = [row for row in rows if not isinstance(row, HealthCheck)]
        if bad:
            raise TypeError(
                f"{PROJECT_CHECKS_ATTRIBUTE} must hold HealthCheck rows; got "
                + ", ".join(type(row).__name__ for row in bad)
            )
        return rows
    default = getattr(module, "APPLICABILITY", UNIVERSAL)
    if not isinstance(default, CheckApplicability):
        raise TypeError(
            "APPLICABILITY must be a CheckApplicability; got "
            f"{type(default).__name__}"
        )
    rows = []
    for attribute in sorted(vars(module)):
        if not attribute.startswith(CHECK_FUNCTION_PREFIX):
            continue
        fn = getattr(module, attribute)
        if not callable(fn):
            continue
        rows.append(HealthCheck(
            slug=_slug_for(attribute),
            name=_name_for(attribute, fn),
            fn=fn,
            applicability=getattr(fn, "applicability", default),
        ))
    return rows


def _slug_for(attribute: str) -> str:
    return attribute[len(CHECK_FUNCTION_PREFIX):].replace("_", "-")


def _name_for(attribute: str, fn) -> str:
    doc = (fn.__doc__ or "").strip()
    if doc:
        return doc.splitlines()[0].strip()
    return _slug_for(attribute).replace("-", " ").capitalize()


__all__ = [
    "CHECK_FILE_GLOB",
    "CHECK_FUNCTION_PREFIX",
    "Discovery",
    "DiscoveryFailure",
    "PROJECT_CHECKS_ATTRIBUTE",
    "PROJECT_CHECKS_DIR",
    "PROJECT_CHECKS_PACKAGE",
    "discover_project_checks",
    "load_check_module",
    "project_checks_dir",
    "register_project_checks_package",
]
