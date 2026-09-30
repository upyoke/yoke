"""Import named modules from the active source checkout and report each origin.

This is the sanctioned smoke test for source an agent is editing: "do the
modules I just added import, and did they import from *my* lane?" Both halves
matter. An import probe that succeeds against an installed copy proves nothing
about the checkout under edit, so every verdict names the file that actually
answered the import and refuses an origin resolved outside the checkout.

The checkout is the repository root above the working directory, because the
command is reached through ``yoke dev run``, which sets the child's working
directory and ``PYTHONPATH`` from the session's claimed lane. There is no path
argument: the authority here is the live ``sys.path``, and reporting a directory
the importer did not consult would be the confabulation this command exists to
close.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _source_pythonpath

#: Marker Python uses for a module caught mid-initialisation by a cycle.
_PARTIAL_INIT_MARKERS = ("partially initialized module", "circular import")


@dataclass(frozen=True)
class ImportOutcome:
    """One module's verdict, with the file that answered the import."""

    module: str
    origin: str
    error: str

    @property
    def ok(self) -> bool:
        return not self.error


def _checkout_root(start: Path | None = None) -> tuple[Path | None, str | None]:
    """Return the Yoke source checkout the importer is bound to."""
    root = _source_pythonpath.repo_root(start)
    if not _source_pythonpath.is_yoke_shaped_tree(root):
        return None, (
            f"{root} is not a Yoke source checkout, so no import it answers "
            "can be attributed to a lane"
        )
    return root, None


def _checkout_frame(exc: BaseException, root: Path) -> str:
    """Name the deepest traceback frame inside *root*, which owns the failure."""
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        try:
            Path(frame.filename).resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        return f"{frame.filename}:{frame.lineno}"
    return ""


def _diagnose(module: str, exc: BaseException, root: Path) -> str:
    """Turn one import failure into a named reason plus its recovery step."""
    detail = str(exc).strip() or type(exc).__name__
    frame = _checkout_frame(exc, root)
    where = f" at {frame}" if frame else ""
    if isinstance(exc, ModuleNotFoundError) and exc.name:
        missing = exc.name
        if missing == module or module.startswith(f"{missing}."):
            return (
                f"no module named {missing!r} under this checkout's source "
                f"roots. Recovery: confirm the file exists and the package "
                f"name matches its directory under {root}."
            )
        return (
            f"imports {missing!r}, which is not installed or not importable"
            f"{where}. Recovery: add the dependency, or correct the import "
            f"to a module this checkout owns."
        )
    if isinstance(exc, ImportError) and any(
        marker in detail for marker in _PARTIAL_INIT_MARKERS
    ):
        return (
            f"circular import: {detail}{where}. Recovery: move the shared "
            "name into a module both sides import, or defer one import into "
            "the function that needs it."
        )
    if isinstance(exc, ImportError):
        return (
            f"{type(exc).__name__}: {detail}{where}. Recovery: correct the "
            "import, or the module it names."
        )
    return (
        f"raised {type(exc).__name__} while executing at import time: "
        f"{detail}{where}. Recovery: module-level code runs on import — move "
        "the work that failed into a function the caller invokes."
    )


def check_module(module: str, *, root: Path) -> ImportOutcome:
    """Import one module and attribute the answer to a file under *root*."""
    try:
        imported = importlib.import_module(module)
    except BaseException as exc:  # noqa: BLE001 - any import-time failure counts
        return ImportOutcome(module, "", _diagnose(module, exc, root))
    origin = getattr(imported, "__file__", None)
    if not origin:
        return ImportOutcome(
            module,
            "",
            f"resolved to a namespace package with no source file. Recovery: "
            f"name a module, or add an __init__.py so {module!r} has one "
            "definite origin.",
        )
    resolved = Path(origin).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return ImportOutcome(
            module,
            str(resolved),
            f"imported from outside this checkout: {resolved}. Recovery: this "
            f"verdict says nothing about {root} — run the probe through "
            f"`{_source_pythonpath.SOURCE_RUN_RECIPE}` from a session that "
            "owns the source lane.",
        )
    return ImportOutcome(module, str(resolved), "")


def run(modules: Sequence[str], *, root: Path) -> int:
    """Probe every named module, then report the failures together."""
    checkout = Path(root).resolve()
    # Every line is flushed as it is written: stdout is block-buffered when the
    # command is captured to a file, and an unflushed header would land after
    # the unbuffered stderr failures it is the context for.
    print(
        f"import-check: importing {len(modules)} module(s) from {checkout}",
        flush=True,
    )
    outcomes = [check_module(module, root=checkout) for module in modules]
    for outcome in outcomes:
        if outcome.ok:
            relative = Path(outcome.origin).relative_to(checkout)
            print(
                f"import-check: ok      {outcome.module} -> {relative}",
                flush=True,
            )
        else:
            print(
                f"import-check: FAILED  {outcome.module}",
                file=sys.stderr,
                flush=True,
            )
            print(f"  reason: {outcome.error}", file=sys.stderr, flush=True)
    failed = [outcome for outcome in outcomes if not outcome.ok]
    if failed:
        names = ", ".join(outcome.module for outcome in failed)
        print(
            f"import-check: {len(failed)} of {len(outcomes)} module(s) failed "
            f"to import from {checkout}: {names}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(
        f"import-check: all {len(outcomes)} module(s) imported from {checkout}",
        flush=True,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke dev import-check",
        description=(
            "Import each named module from the current session's claimed Yoke "
            "source lane and report the file that answered it. Catches a "
            "circular import, a missing dependency, or module-level code that "
            "raises, without paying for pytest collection."
        ),
    )
    parser.add_argument(
        "module",
        nargs="+",
        metavar="MODULE",
        help=(
            "Import name to probe, e.g. yoke_core.domain.aws_machine_client. "
            "Several are imported in the order given, in one interpreter."
        ),
    )
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root, error = _checkout_root()
    if root is None:
        print(
            "import-check: refusing to attribute an import to a checkout",
            file=sys.stderr,
        )
        print(f"  reason: {error}", file=sys.stderr)
        print(
            f"  recovery: run it as `{_source_pythonpath.SOURCE_RUN_RECIPE}` "
            "from a session that owns a Yoke source lane.",
            file=sys.stderr,
        )
        return 1
    return run(parsed.module, root=root)


__all__ = ["ImportOutcome", "check_module", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
