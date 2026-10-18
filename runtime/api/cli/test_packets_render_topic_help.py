"""``yoke packets render --help`` lists the seed topics."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

from yoke_cli.main import main as cli_main
from yoke_core.domain.schema_api_context_seed import TOPICS


def test_packets_render_help_lists_valid_topics() -> None:
    stdout = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
        rc = cli_main(["packets", "render", "--help"])
    assert rc == 0
    collapsed = " ".join(stdout.getvalue().split())
    assert f"Valid topics: {', '.join(TOPICS)}." in collapsed
