"""Contract coverage for the minimum-serving-version declaration."""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

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


def _committed_in_an_untagged_checkout(root: Path) -> Path:
    """Write one entry into a fresh checkout that carries no release tag.

    A checkout with no tag containing the entry's commit is exactly the state
    an author is in while writing one, which is the state the gate is for.
    """
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    entry = root / "0099_drop_a_column.py"
    entry.write_text("MINIMUM_SERVING_VERSION = '0.1.2'\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(root), "add", entry.name), check=True)
    subprocess.run(
        (
            "git", "-C", str(root),
            "-c", "user.email=test@example.invalid",
            "-c", "user.name=test",
            "commit", "-q", "-m", "add entry",
        ),
        check=True,
    )
    return entry


class TestNextReleaseSentinel:
    """A new destructive entry can only be served by a release that is not cut.

    Every literal an author could write today names a build that predates the
    entry, so a literal on an unreleased entry is always wrong. One such
    declaration named precisely the build that could not read the schema its
    own entry produced, and the compatibility gate believed it.
    """

    def test_the_sentinel_is_a_declaration_not_a_version(self) -> None:
        module = _module(MINIMUM_SERVING_VERSION=serving.NEXT_RELEASE)
        assert serving.declared_minimum(module) == serving.NEXT_RELEASE

    def test_an_unreleased_entry_declaring_a_literal_fails_module_load(
        self, tmp_path
    ) -> None:
        entry = _committed_in_an_untagged_checkout(tmp_path)

        with pytest.raises(serving.ServingVersionError) as excinfo:
            serving.require_declaration(
                "0099_drop_a_column",
                "ALTER TABLE items DROP COLUMN flow",
                _module(MINIMUM_SERVING_VERSION="0.1.2"),
                path=entry,
            )
        message = str(excinfo.value)
        assert "no release contains this entry yet" in message
        assert serving.NEXT_RELEASE in message

    def test_an_unreleased_entry_declaring_the_sentinel_loads(self, tmp_path) -> None:
        entry = _committed_in_an_untagged_checkout(tmp_path)

        declared = serving.require_declaration(
            "0099_drop_a_column",
            "ALTER TABLE items DROP COLUMN flow",
            _module(MINIMUM_SERVING_VERSION=serving.NEXT_RELEASE),
            path=entry,
        )
        assert declared == serving.NEXT_RELEASE

    def test_the_missing_declaration_message_teaches_the_sentinel(self) -> None:
        with pytest.raises(serving.ServingVersionError) as excinfo:
            serving.require_declaration(
                "0099_drop_a_column",
                "ALTER TABLE items DROP COLUMN flow",
                _module(),
            )
        assert serving.NEXT_RELEASE in str(excinfo.value)

    def test_a_built_artifact_outside_a_checkout_keeps_its_literals(
        self, tmp_path
    ) -> None:
        """A wheel ships only released bytes, so its literals are already true.

        Nothing else could be the case: the file exists because a release put
        it there, and no checkout is present to say which release that was.
        """
        entry = tmp_path / "0001_retire_superseded_surfaces.py"
        entry.write_text("", encoding="utf-8")
        assert serving.entry_is_released(entry)

    def test_the_applier_never_refuses_the_sentinel(self) -> None:
        # The artifact applying an entry is by construction one that carries
        # it, which is exactly the claim the sentinel makes.
        serving.refuse_if_behind("0099_drop", "0.0.1", serving.NEXT_RELEASE)


class TestRecordedFloor:
    def test_a_literal_is_recorded_as_authored(self) -> None:
        module = _module(MINIMUM_SERVING_VERSION="0.1.2")
        assert serving.recorded_floor(module, running_version="9.9.9") == "0.1.2"

    def test_the_sentinel_resolves_to_the_applying_artifact(self) -> None:
        module = _module(MINIMUM_SERVING_VERSION=serving.NEXT_RELEASE)
        assert (
            serving.recorded_floor(module, running_version="0.1.1+launch.250")
            == "0.1.1+launch.250"
        )

    def test_an_unresolved_artifact_records_no_floor_rather_than_a_guess(
        self,
    ) -> None:
        module = _module(MINIMUM_SERVING_VERSION=serving.NEXT_RELEASE)
        assert serving.recorded_floor(module, running_version="") is None

    def test_an_entry_with_no_declaration_records_nothing(self) -> None:
        assert serving.recorded_floor(_module(), running_version="0.1.2") is None
