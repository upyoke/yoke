"""Build policy for the yoke-core product wheel."""

from __future__ import annotations

from setuptools import setup
from setuptools.command.build_py import build_py


_TEST_SUPPORT_MARKERS = (
    "_test_fixtures",
    "_test_helpers",
    "_test_schema",
    "_test_support",
)


def _is_test_support(package: str, module: str) -> bool:
    leaf = module.rsplit(".", 1)[-1]
    return (
        ".tests" in package
        or package.endswith(".tests")
        or leaf.startswith("test_")
        or any(marker in leaf for marker in _TEST_SUPPORT_MARKERS)
    )


class ProductBuildPy(build_py):
    """Keep source-tree test helpers out of the installed engine wheel."""

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [
            entry
            for entry in modules
            if not _is_test_support(entry[0], entry[1])
        ]


setup(cmdclass={"build_py": ProductBuildPy})
