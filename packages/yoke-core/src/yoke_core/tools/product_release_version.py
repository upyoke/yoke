"""Canonical commit-clock version policy for product wheels."""

from yoke_contracts.release_version import release_version


def assert_release_version(version: str) -> None:
    """Require the shared BASE.YYYYMMDDHHMM spelling."""
    release_version(version)
