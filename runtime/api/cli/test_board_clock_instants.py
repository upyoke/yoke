"""Generated board metadata agrees across CLI and engine file boundaries."""

import pytest

from yoke_cli.board import rebuild as cli
from yoke_contracts import timestamps
from yoke_core.domain import rebuild_board_render as engine

WIRE = "2026-07-14T00:00:00.123456Z"
CLOCK = timestamps.parse_instant("2026-07-14T05:45:00.123456+05:45")


@pytest.mark.parametrize("owner", [cli, engine])
@pytest.mark.parametrize("existing", [False, True])
def test_generated_marker_qualifies_microseconds_and_preserves_authored_bytes(
    owner, existing, tmp_path, monkeypatch
):
    path = tmp_path / "BOARD.md"
    authored = "# Authored notes\n\nZoë — keep these bytes\n"
    if existing:
        path.write_text(authored)
    monkeypatch.setattr(timestamps, "utc_now", lambda: CLOCK)
    monkeypatch.setattr(engine, "utc_now", lambda: CLOCK)
    monkeypatch.setattr(owner, "fetch_and_render", lambda *args: "### Live board\n")
    before = path.read_bytes() if existing else None
    rendered = owner.build_board_file_text(
        repo_root=tmp_path, board_path=path, scope="all", phase_recorder=None
    )
    assert "last synced: " + WIRE in rendered
    assert "### Live board" in rendered
    if existing:
        assert authored in rendered
        assert path.read_bytes() == before
    else:
        assert not path.exists()
