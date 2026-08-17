"""Built product-wheel metadata integrity proof."""

from __future__ import annotations

import zipfile
from pathlib import Path

from packaging.requirements import Requirement

from yoke_core.tools import (
    package_index,
    wheel_module_completeness,
    wheel_record_validation,
    wheel_sibling_pins,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_built_product_wheels_pin_sibling_requires_dist(
    product_wheelhouse: Path,
) -> None:
    product_records = [
        record
        for record in package_index.read_wheel_records(product_wheelhouse)
        if record.canonical_name in package_index.PRODUCT_PACKAGE_NAMES
    ]
    versions = {record.version for record in product_records}
    assert len(versions) == 1, versions
    version = versions.pop()

    for record in product_records:
        wheel = product_wheelhouse / record.filename
        requirements = [
            Requirement(raw) for raw in wheel_sibling_pins.wheel_requires_dist(wheel)
        ]
        wheel_sibling_pins.assert_wheel_siblings_pinned(
            wheel, package_index.PRODUCT_PACKAGE_NAMES, version
        )
        wheel_record_validation.assert_wheel_record_valid(wheel)
        if record.canonical_name == "yoke-core":
            assert any(
                requirement.name == "packaging" for requirement in requirements
            ), "yoke-core must declare its direct packaging dependency"
            tomli = next(
                requirement
                for requirement in requirements
                if requirement.name == "tomli"
            )
            assert tomli.marker is not None
            assert tomli.marker.evaluate({"python_version": "3.10"})
            assert not tomli.marker.evaluate({"python_version": "3.11"})


def test_yoke_core_wheel_carries_universe_app_runtime_and_types(
    product_wheelhouse: Path,
) -> None:
    wheel = next(product_wheelhouse.glob("yoke_core-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
    assert not any(member.endswith(".pyc") for member in members)
    for member in (
        "yoke_core/ui/static/app.js",
        "yoke_core/ui/static/contract.js",
        "yoke_core/ui/static/contract-version.js",
        "yoke_core/ui/static/mount-options.js",
        "yoke_core/ui/static/universe_navigation.js",
        "yoke_core/ui/static/universe_views.js",
        "yoke_core/ui/static/shell.css",
        "yoke_core/ui/contracts/universe-app.ts",
        "yoke_core/ui/contracts/universe-app.d.ts",
        "yoke_core/ui/contracts/tsconfig.json",
    ):
        assert member in members


def test_yoke_core_wheel_carries_hooks_without_source_test_helpers(
    product_wheelhouse: Path,
) -> None:
    wheel = next(product_wheelhouse.glob("yoke_core-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
    for member in (
        "yoke_core/hooks/local_entry.py",
        "yoke_core/hooks/runner.py",
        "yoke_core/hooks/session_dispatch.py",
        "yoke_core/hooks/telemetry.py",
        "yoke_core/domain/machine_verification_schema.py",
    ):
        assert member in members
    assert "yoke_core/domain/test_machine_schema.py" not in members
    test_markers = (
        "_test_fixtures.py",
        "_test_helpers.py",
        "_test_schema.py",
        "_test_support.py",
    )
    leaked = sorted(
        member
        for member in members
        if member.startswith("yoke_core/")
        and not member.startswith("yoke_core/install_bundle_tree/")
        and member.endswith(".py")
        and ("/tests/" in member or member.endswith(test_markers))
    )
    assert leaked == []


def test_yoke_core_wheel_matches_source_runtime_modules(
    product_wheelhouse: Path,
) -> None:
    wheel = next(product_wheelhouse.glob("yoke_core-*.whl"))
    package_root = REPO_ROOT / "packages/yoke-core/src/yoke_core"

    wheel_module_completeness.assert_wheel_module_completeness(package_root, wheel)
