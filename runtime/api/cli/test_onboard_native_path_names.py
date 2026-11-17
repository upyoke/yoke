"""Checkout defaults use the final native folder on every host OS."""

from pathlib import PureWindowsPath

import pytest

from yoke_cli.config.onboard_wizard_project_fields import slug_from_checkout


@pytest.mark.parametrize("checkout", [
    PureWindowsPath(r"C:\Users\ben\code\widget"),
    PureWindowsPath("C:/Users/ben/code/widget/"),
    PureWindowsPath("C:\\Users\\ben\\code\\widget\\"),
    PureWindowsPath(r"\\server\share\widget"),
])
def test_windows_checkout_suggests_only_the_folder(checkout):
    assert slug_from_checkout(str(checkout)) == "widget"


@pytest.mark.parametrize(("checkout", "expected"), [
    ("C:\\Users\\ben\\code\\widget\\", "widget"),
    ("/home/ben/code/widget/", "widget"),
    (r"C:\code\My Widget!", "my-widget"),
    ("widget", "widget"),
    ("C:\\", "project"),
    ("/", "project"),
    ("", "project"),
    (None, "project"),
])
def test_checkout_slug_normalization(checkout, expected):
    assert slug_from_checkout(checkout) == expected
