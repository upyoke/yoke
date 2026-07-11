"""Version policy for product wheels served beside public dependencies."""

from __future__ import annotations

from packaging.version import Version


def assert_public_index_unforgeable(version: str) -> None:
    """Require a version string that PyPI cannot host for a same-named project."""

    if Version(version).local is None:
        raise ValueError(
            "product release version must include a PEP 440 local segment: "
            f"{version}"
        )
