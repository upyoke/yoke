"""Build policy for the yoke-core product wheel."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

_PROJECT_ROOT = Path(__file__).resolve().parent
_SOURCE_ROOT = _PROJECT_ROOT / "src"
_BUNDLE_REL = Path("yoke_core/install_bundle_tree")
sys.path.insert(0, str(_SOURCE_ROOT))
from yoke_core.tools.wheel_module_completeness import is_test_support  # noqa: E402


def _write_bundle_tree(dest: Path) -> list[str]:
    """Build ``yoke_core.install_bundle_tree`` into ``dest``.

    A source checkout builds it from the repo-root sources. An unpacked sdist
    (``PKG-INFO`` at its root, no checkout around it) copies the tree its
    sdist build carried.
    """
    if (_PROJECT_ROOT / "PKG-INFO").is_file():
        carried = _SOURCE_ROOT / _BUNDLE_REL
        if not (carried / "__init__.py").is_file():
            raise SystemExit(
                f"install_bundle_sdist_tree_missing: {carried}. Rebuild the "
                "sdist from a full Yoke source checkout."
            )
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(carried, dest)
        return [str(p) for p in sorted(dest.rglob("*")) if p.is_file()]
    sys.path.insert(0, str(_PROJECT_ROOT.parent / "yoke-contracts" / "src"))
    from yoke_core.domain.install_bundle_tree_build import (
        InstallBundleTreeError,
        write_tree,
    )

    try:
        return write_tree(target_root=_PROJECT_ROOT.parents[1], dest=dest)
    except InstallBundleTreeError as exc:
        raise SystemExit(f"yoke-core install-bundle build refused: {exc}") from exc


class ProductBuildPy(build_py):
    """Keep test helpers out of the wheel and build its install-bundle tree."""

    def run(self):
        # Setuptools reuses build/lib between local invocations. Remove that
        # staging tree so a module deleted or newly excluded from source cannot
        # survive into a later wheel and conceal an incomplete clean build.
        shutil.rmtree(Path(self.build_lib), ignore_errors=True)
        super().run()
        self._bundle_outputs = (
            []
            if self.editable_mode
            else _write_bundle_tree(Path(self.build_lib) / _BUNDLE_REL)
        )

    def get_outputs(self, include_bytecode=True):
        outputs = super().get_outputs(include_bytecode)
        return [*outputs, *getattr(self, "_bundle_outputs", [])]

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [entry for entry in modules if not is_test_support(entry[0], entry[1])]


class ProductSdist(sdist):
    """Carry the built install-bundle tree, since an sdist has no checkout."""

    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        _write_bundle_tree(Path(base_dir) / "src" / _BUNDLE_REL)


setup(cmdclass={"build_py": ProductBuildPy, "sdist": ProductSdist})
