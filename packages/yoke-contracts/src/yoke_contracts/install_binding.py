"""Install-binding vocabulary and Yoke source-checkout detection.

The install binding is a property of a running import: a package
imported from inside a checkout's ``packages/`` source tree is bound to
that checkout; anywhere else (site-packages of a wheel install) it runs
as a packaged wheel. Two status surfaces report it — the CLI-local
``yoke status`` (binding of the running ``yoke_cli`` import) and the
``status.run`` handler twin in yoke-core (binding of the running
``yoke_core`` import) — so the vocabulary and detector live here, where
both packages can import them, and the two reports keep one JSON shape.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution as _distribution
from pathlib import Path
from typing import Any, Mapping, Optional, Union

KIND_PACKAGED_WHEEL = "packaged_wheel"
KIND_SOURCE_CHECKOUT = "source_checkout"

# Directory that holds the per-package source roots inside a Yoke checkout
# (``<root>/packages/<dist>/src/<package>/...``).
CHECKOUT_PACKAGES_DIR_NAME = "packages"


def is_yoke_source_checkout(root: Path) -> bool:
    """True iff *root* looks like the Yoke source checkout."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return 'name = "yoke"' in text and (root / "runtime" / "harness").is_dir()


def source_checkout_root(module_file: Union[str, Path]) -> Optional[Path]:
    """The Yoke source checkout *module_file* physically lives in, or ``None``.

    A wheel install resolves from site-packages, which never sits inside a
    checkout's ``packages/`` tree — even when the venv itself lives inside a
    checkout — so requiring a ``packages`` ancestor whose parent is a real
    Yoke checkout separates the two shapes without false positives.
    """
    for parent in Path(module_file).parents:
        if parent.name != CHECKOUT_PACKAGES_DIR_NAME:
            continue
        root = parent.parent
        if is_yoke_source_checkout(root):
            return root
    return None


def distribution_version_for_module(
    distribution_name: str,
    module_file: Union[str, Path, None],
    *,
    source_value: str = "",
) -> str:
    """Return metadata version only when it owns ``module_file``.

    Distribution metadata is process-global, while imports can be rebound by
    ``PYTHONPATH`` or an editable checkout.  Looking up a distribution name
    alone can therefore report an unrelated wheel's version for source code
    loaded from elsewhere. Source checkouts return ``source_value``; packaged
    modules return a version only when their origin is under the matching
    distribution's installed root.
    """

    if not module_file:
        return ""
    try:
        module_path = Path(module_file).resolve()
    except (OSError, TypeError, ValueError):
        return ""
    if source_checkout_root(module_path):
        return source_value
    try:
        installed = _distribution(distribution_name)
        distribution_root = Path(installed.locate_file("")).resolve()
    except (PackageNotFoundError, OSError, TypeError, ValueError):
        return ""
    if not module_path.is_relative_to(distribution_root):
        return ""
    files = installed.files
    if not files:
        return ""
    try:
        owns_module = any(
            Path(installed.locate_file(file)).resolve() == module_path
            for file in files
        )
    except (OSError, TypeError, ValueError):
        return ""
    if not owns_module:
        return ""
    return str(installed.version or "")


def label(binding: Mapping[str, Any]) -> str:
    """One-line factual label for an install-binding mapping."""

    if binding.get("kind") == KIND_SOURCE_CHECKOUT:
        return f"source checkout {binding.get('checkout_root')}"
    return f"packaged wheel {binding.get('version') or '<unknown version>'}"


__all__ = [
    "CHECKOUT_PACKAGES_DIR_NAME",
    "KIND_PACKAGED_WHEEL",
    "KIND_SOURCE_CHECKOUT",
    "distribution_version_for_module",
    "is_yoke_source_checkout",
    "label",
    "source_checkout_root",
]
