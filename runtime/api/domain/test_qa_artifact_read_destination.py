"""A read's destination is private and unique, not a predictable shared name.

An artifact id is unique only inside the control plane that issued it, and
the machine temp root is shared with every process on the box, so the pair
"temp root + artifact id" is neither unique nor unguessable. These pin the
two properties the destination has to keep.
"""

from __future__ import annotations

import stat

from yoke_contracts.free_paths import is_under_free_path_prefix, private_free_path
from yoke_contracts.qa_artifact_read import artifact_read_destination


def test_two_reads_of_one_artifact_id_never_share_a_path() -> None:
    first = artifact_read_destination(17980, content_type="image/png")
    second = artifact_read_destination(17980, content_type="image/png")

    assert first != second
    assert first.parent != second.parent
    # The readable name survives; only the enclosing directory differs, so a
    # second universe's artifact 17980 cannot land on the first one's bytes.
    assert first.name == second.name == "qa-artifact-17980.png"


def test_the_enclosing_directory_is_private_and_already_created() -> None:
    destination = artifact_read_destination(17980, content_type="image/png")

    assert destination.parent.is_dir()
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    # The caller writes the file; nothing pre-creates it under that name.
    assert not destination.exists()


def test_the_destination_stays_inside_a_guard_admitted_root() -> None:
    destination = artifact_read_destination(17980, content_type="image/png")

    assert is_under_free_path_prefix(destination)


def test_a_traversing_filename_is_refused_rather_than_resolved() -> None:
    for candidate in ("../escape.png", "nested/shot.png", "", "."):
        try:
            private_free_path(candidate, prefix="yoke-qa-artifact.")
        except ValueError as exc:
            assert "one segment" in str(exc)
        else:
            raise AssertionError(f"accepted a non-segment filename: {candidate!r}")
