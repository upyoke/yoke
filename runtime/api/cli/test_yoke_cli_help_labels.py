"""Help-output product-boundary labels for the in-checkout CLI."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from yoke_cli.main import main as cli_main


def test_top_help_labels_non_product_dispositions() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["--help"])
    out = buf.getvalue()

    assert rc == 0
    assert "yoke dev setup [source-dev/admin]" in out
    assert "yoke dev db-admin setup [source-dev/admin]" in out
    assert "yoke qa browser run [client-local]" in out
    assert "yoke git pre-commit [hook-local]" in out
    assert "yoke status\n" in out
    assert "yoke self-host import ARCHIVE [--dir D] [--yes] [--json]" in out
    assert not any(
        line.startswith("    yoke status [")
        for line in out.splitlines()
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    (
        (["dev", "--help"], "yoke dev setup [source-dev/admin]"),
        (["agents", "--help"], "yoke agents render [source-dev/admin]"),
        (["packets", "--help"], "yoke packets check [source-dev/admin]"),
        (["merge", "--help"], "yoke merge audit [source-dev/admin]"),
        (["qa", "browser", "--help"], "yoke qa browser run [client-local]"),
        (
            ["github-actions", "--help"],
            "yoke github-actions secret set [source-dev/admin]",
        ),
    ),
)
def test_group_help_labels_non_product_dispositions(args, expected) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(args)

    assert rc == 0
    assert expected in buf.getvalue()
