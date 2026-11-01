"""An incompatible catalog reader must not call a dump corrupt."""

from pathlib import Path

import pytest

from yoke_core.domain.universe_portability_common import ArchiveInvalidError
from yoke_core.domain.universe_portability_inspection import inspect_archive


@pytest.mark.parametrize("unsupported", [False, True])
def test_catalog_reader_distinguishes_tool_version_from_corrupt_payload(tmp_path, unsupported):
    message = (
        "pg_restore: error: unsupported version (1.16) in file header"
        if unsupported else "pg_restore: error: could not read from input file: end of file"
    )
    executable: Path = tmp_path / "pg_restore"
    executable.write_text(f"#!/usr/bin/env python3\nimport sys\nsys.stderr.write({message!r})\nsys.exit(1)\n")
    executable.chmod(0o700)
    archive = tmp_path / "universe.dump"
    archive.write_bytes(b"PGDMP" + b"test payload")
    with pytest.raises(ArchiveInvalidError) as caught:
        inspect_archive(archive, pg_restore=str(executable))
    refusal = str(caught.value)
    if unsupported:
        assert "archive_tool_version_unsupported" in refusal
        assert "matching the source dump writer or newer" in refusal
        assert "preserve the original archive and receipt" in refusal
        assert "corrupt" not in refusal
    else:
        assert "corrupt or unreadable" in refusal
        assert "end of file" in refusal
        assert "archive_tool_version_unsupported" not in refusal
