"""Contract coverage for the minimum-serving-version declaration."""

from __future__ import annotations

import types

import pytest

from yoke_core.domain import migration_serving_version as serving


def _module(**attributes: object) -> types.ModuleType:
    module = types.ModuleType("entry_under_test")
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


class TestSurfaceRemovalDetection:
    def test_drop_column_is_a_surface_removal(self) -> None:
        assert serving.removes_a_surface('ALTER TABLE "items" DROP COLUMN "flow"')

    def test_drop_table_is_a_surface_removal(self) -> None:
        assert serving.removes_a_surface("conn.execute('DROP TABLE wrapup_reports')")

    def test_detection_is_case_insensitive(self) -> None:
        assert serving.removes_a_surface("alter table items drop column flow")

    def test_additive_ddl_is_not_a_surface_removal(self) -> None:
        assert not serving.removes_a_surface("ALTER TABLE items ADD COLUMN note TEXT")


class TestDeclaration:
    def test_absent_declaration_reads_as_none(self) -> None:
        assert serving.declared_minimum(_module()) is None

    def test_blank_declaration_reads_as_none(self) -> None:
        assert serving.declared_minimum(_module(MINIMUM_SERVING_VERSION="  ")) is None

    def test_declared_version_is_returned(self) -> None:
        module = _module(MINIMUM_SERVING_VERSION="0.1.2")
        assert serving.declared_minimum(module) == "0.1.2"

    def test_unparseable_declaration_is_refused(self) -> None:
        module = _module(MINIMUM_SERVING_VERSION="not-a-version")
        with pytest.raises(serving.ServingVersionError):
            serving.declared_minimum(module)


class TestAuthoringGate:
    def test_surface_removal_without_a_declaration_fails_authoring(self) -> None:
        with pytest.raises(serving.ServingVersionError) as excinfo:
            serving.require_declaration(
                "0001_retire_superseded_surfaces",
                "ALTER TABLE items DROP COLUMN flow",
                _module(),
            )
        message = str(excinfo.value)
        assert "0001_retire_superseded_surfaces" in message
        assert serving.DECLARATION_ATTRIBUTE in message

    def test_surface_removal_with_a_declaration_passes(self) -> None:
        declared = serving.require_declaration(
            "0001_retire_superseded_surfaces",
            "ALTER TABLE items DROP COLUMN flow",
            _module(MINIMUM_SERVING_VERSION="0.1.2"),
        )
        assert declared == "0.1.2"

    def test_additive_entry_needs_no_declaration(self) -> None:
        declared = serving.require_declaration(
            "0005_add_a_column",
            "ALTER TABLE items ADD COLUMN note TEXT",
            _module(),
        )
        assert declared is None


class TestComparison:
    def test_local_segments_order_correctly(self) -> None:
        assert serving.satisfies_minimum("0.1.1+launch.180", "0.1.1+launch.169")
        assert not serving.satisfies_minimum("0.1.1+launch.169", "0.1.1+launch.180")

    def test_equal_versions_satisfy_the_floor(self) -> None:
        assert serving.satisfies_minimum("0.1.2", "0.1.2")

    def test_empty_running_version_is_unresolved(self) -> None:
        assert serving.version_is_unresolved("")
        assert serving.version_is_unresolved("   ")
        assert not serving.version_is_unresolved("0.1.2")


class TestApplierRefusal:
    def test_build_behind_the_declared_floor_is_refused(self) -> None:
        with pytest.raises(serving.ServingVersionError) as excinfo:
            serving.refuse_if_behind("0001_retire", "0.1.1", "0.1.2")
        message = str(excinfo.value)
        assert "0001_retire" in message
        assert "0.1.2" in message
        assert "0.1.1" in message

    def test_build_at_or_past_the_floor_applies(self) -> None:
        serving.refuse_if_behind("0001_retire", "0.1.2", "0.1.2")
        serving.refuse_if_behind("0001_retire", "0.2.0", "0.1.2")

    def test_entry_without_a_floor_always_applies(self) -> None:
        serving.refuse_if_behind("0005_add_a_column", "0.0.1", None)

    def test_source_checkout_is_never_refused(self) -> None:
        """A tree whose version is unresolved is ahead, not behind.

        Refusing here would brick every developer machine and every test run
        on the entry that tree just authored.
        """
        serving.refuse_if_behind("0001_retire", "", "99.0.0")
