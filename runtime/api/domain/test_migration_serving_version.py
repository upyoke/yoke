"""Contract coverage for the minimum-serving-version declaration."""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from yoke_core.domain import migration_serving_version as serving
from yoke_core.domain.migration_history import load_migration_module


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


#: A destructive entry as a release ships it: a literal floor that was true
#: when the release carrying it was cut, and DDL that removes a surface.
_RELEASED_ENTRY_SOURCE = (
    "MINIMUM_SERVING_VERSION = '0.1.1+launch.181'\n"
    "\n"
    "def apply(conn):\n"
    "    conn.execute('ALTER TABLE \"items\" DROP COLUMN \"flow\"')\n"
)


def _commit(root: Path, message: str) -> None:
    subprocess.run(
        (
            "git", "-C", str(root),
            "-c", "user.email=test@example.invalid",
            "-c", "user.name=test",
            "commit", "-q", "-m", message,
        ),
        check=True,
    )


def _committed_in_an_untagged_checkout(root: Path) -> Path:
    """Write one entry into a fresh checkout that carries no release tag.

    A checkout with no tag containing the entry's commit is exactly the state
    an author is in while writing one, which is the state the gate is for.
    """
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    entry = root / "0099_drop_a_column.py"
    entry.write_text("MINIMUM_SERVING_VERSION = '0.1.2'\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(root), "add", entry.name), check=True)
    _commit(root, "add entry")
    return entry


def _installed_beneath_an_unrelated_checkout(root: Path) -> Path:
    """Unpack one released entry where an installed package normally lands.

    A virtualenv under some project's own repository. That repository has
    never tracked the entry, so it answers about it exactly as it would about
    a file that does not exist — while the bytes are as released as bytes get.
    """
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    tracked = root / "README.md"
    tracked.write_text("a project depending on this package\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(root), "add", tracked.name), check=True)
    _commit(root, "add a tracked file")
    installed = root / ".venv" / "site-packages" / "migrations"
    installed.mkdir(parents=True)
    entry = installed / "0001_retire_superseded_surfaces.py"
    entry.write_text(_RELEASED_ENTRY_SOURCE, encoding="utf-8")
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

    def test_an_installed_entry_under_a_foreign_checkout_stays_released(
        self, tmp_path
    ) -> None:
        """Being inside a work tree is not the same as being its source."""
        entry = _installed_beneath_an_unrelated_checkout(tmp_path)

        assert serving.entry_is_released(entry)

    def test_an_installed_entry_keeps_its_literal_through_the_gate(
        self, tmp_path
    ) -> None:
        entry = _installed_beneath_an_unrelated_checkout(tmp_path)

        declared = serving.require_declaration(
            "0001_retire_superseded_surfaces",
            entry.read_text(encoding="utf-8"),
            _module(MINIMUM_SERVING_VERSION="0.1.1+launch.181"),
            path=entry,
        )
        assert declared == "0.1.1+launch.181"

    def test_an_installed_history_loads_for_a_birth_that_stamps_it(
        self, tmp_path
    ) -> None:
        """Birth loads every entry before stamping it, and refusing bricks it.

        A released engine whose packages sat under a checkout could not bring
        up a new database at all: the gate read the surrounding repository's
        silence about a file it had never tracked as proof that no release
        carried the entry the running artifact was shipping.
        """
        entry = _installed_beneath_an_unrelated_checkout(tmp_path)

        module = load_migration_module(entry, "0001_retire_superseded_surfaces")

        assert module.MINIMUM_SERVING_VERSION == "0.1.1+launch.181"

    def test_an_uncommitted_entry_beside_tracked_siblings_is_unreleased(
        self, tmp_path
    ) -> None:
        """A history the checkout owns still answers for one being written."""
        sibling = _committed_in_an_untagged_checkout(tmp_path)
        authored = sibling.parent / "0100_drop_another_column.py"
        authored.write_text(_RELEASED_ENTRY_SOURCE, encoding="utf-8")

        assert not serving.entry_is_released(authored)

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
