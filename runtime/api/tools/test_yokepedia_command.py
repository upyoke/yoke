"""``yoke dev yokepedia`` builds through the scanner path, then opens the page."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.tools import yokepedia


@pytest.fixture
def built(monkeypatch, tmp_path: Path):
    """A resolved checkout whose build succeeds; returns the build mock."""
    monkeypatch.setattr(
        yokepedia.source_dev_scanner, "checkout_root", lambda: (tmp_path, None)
    )
    build = mock.Mock(return_value=0)
    monkeypatch.setattr(yokepedia.source_dev_run, "run", build)
    return build


def test_no_open_builds_through_the_scanner_and_prints_the_path(
    built, monkeypatch, tmp_path, capsys
):
    browser = mock.Mock()
    monkeypatch.setattr(yokepedia.webbrowser, "open", browser)
    assert yokepedia.main(["--no-open"]) == 0
    built.assert_called_once_with(["python3", "docs/teaching/tools/build.py"])
    assert capsys.readouterr().out.strip() == str(tmp_path / yokepedia.PAGE)
    browser.assert_not_called()


def test_opens_the_page_as_a_file_url(built, monkeypatch, tmp_path, capsys):
    browser = mock.Mock(return_value=True)
    monkeypatch.setattr(yokepedia.webbrowser, "open", browser)
    assert yokepedia.main([]) == 0
    page = tmp_path / yokepedia.PAGE
    browser.assert_called_once_with(page.as_uri())
    assert f"Opened Yokepedia: {page}" in capsys.readouterr().out


@pytest.mark.parametrize("outcome", [False, yokepedia.webbrowser.Error("no browser")])
def test_unopenable_browser_prints_the_path_and_succeeds(
    built, monkeypatch, tmp_path, capsys, outcome
):
    browser = mock.Mock(
        **(
            {"side_effect": outcome}
            if isinstance(outcome, Exception)
            else {"return_value": outcome}
        )
    )
    monkeypatch.setattr(yokepedia.webbrowser, "open", browser)
    assert yokepedia.main([]) == 0
    out = capsys.readouterr().out
    assert (
        f"Could not open a browser. Open this file: {tmp_path / yokepedia.PAGE}" in out
    )


def test_build_failure_exits_nonzero_and_never_opens(built, monkeypatch, capsys):
    built.return_value = 1
    browser = mock.Mock()
    monkeypatch.setattr(yokepedia.webbrowser, "open", browser)
    assert yokepedia.main([]) == 1
    assert "yokepedia_build_failed" in capsys.readouterr().err
    browser.assert_not_called()


def test_outside_a_checkout_refuses_before_building(monkeypatch, tmp_path, capsys):
    build = mock.Mock()
    monkeypatch.setattr(yokepedia.source_dev_run, "run", build)
    monkeypatch.chdir(tmp_path)
    assert yokepedia.main(["--no-open"]) == 1
    err = capsys.readouterr().err
    assert "not_yoke_source_checkout" in err
    assert "cd into a Yoke source checkout" in err
    build.assert_not_called()


def test_registered_beside_other_source_development_commands():
    from yoke_cli import operation_inventory
    from yoke_cli.commands.installer_local import (
        TOOL_SHAPED_SUBCOMMANDS,
        TOOL_SHAPED_USAGE,
    )

    assert ("dev", "yokepedia") in TOOL_SHAPED_SUBCOMMANDS
    assert TOOL_SHAPED_USAGE["yoke dev yokepedia"] == yokepedia.USAGE
    assert operation_inventory.lookup("yoke dev yokepedia") is not None
