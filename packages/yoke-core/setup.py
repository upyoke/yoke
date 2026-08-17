"""Build policy for the yoke-core product wheel."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

_SOURCE_ROOT = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(_SOURCE_ROOT))
from yoke_core.tools.wheel_module_completeness import is_test_support  # noqa: E402


class ProductBuildPy(build_py):
    """Keep source-tree test helpers out of the installed engine wheel."""

    def run(self):
        # Setuptools reuses build/lib between local invocations. Remove that
        # staging tree so a module deleted or newly excluded from source cannot
        # survive into a later wheel and conceal an incomplete clean build.
        shutil.rmtree(Path(self.build_lib), ignore_errors=True)
        super().run()

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [entry for entry in modules if not is_test_support(entry[0], entry[1])]


setup(cmdclass={"build_py": ProductBuildPy})
