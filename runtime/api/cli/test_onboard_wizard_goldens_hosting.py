"""Textual SVG golden gates for the Hosting onboarding screens.

Each gate drives the real flow to one Hosting screen and asserts its exported
SVG byte-for-byte against ``__snapshots__``. The published build version and
the machine home are pinned so the one-click link and the custody path read
the same on every machine; no gate writes a secret or reaches AWS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_golden_support import (  # noqa: E402
    assert_golden,
    make_app,
    render,
)
from yoke_cli.config import aws_admin_capability  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402

_TITLE = "yoke onboard · Hosting"
# Pinned so the link's version segment is deterministic; the golden normalizer
# rewrites it to {{VERSION}}, and a fixed length keeps the SVG coordinates
# stable the way the install-summary gate does.
_PINNED_VERSION = "0.1.0"
_STUB_ACCOUNT = "123456789012"
_STUB_IDENTITY = "yoke-aws-admin"


@pytest.fixture(autouse=True)
def _pin_build_and_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        aws_admin_capability, "build_version", lambda: _PINNED_VERSION,
    )
    monkeypatch.setattr(
        aws_admin_capability, "default_region", lambda: "us-east-1",
    )
    # The custody line names the secrets directory; anchor it off a fixed home
    # so the rendered path is machine-independent.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/home/operator")))
    monkeypatch.setenv("YOKE_MACHINE_HOME", "/home/operator/.yoke")


def _seed_project(app: Any) -> None:
    app.result.project_mode = onboard_project.PROJECT_MODE_CREATE_REPO
    app.result.project_slug = "acme-app"
    app.result.project_name = "Acme App"


def test_hosting_provider_choice() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_hosting()

    assert_golden("hosting_provider_choice", render(app, drive, title=_TITLE))


def test_hosting_aws_sign_in() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_hosting()
        a._on_hosting_provider_choice("aws")

    assert_golden("hosting_aws_sign_in", render(app, drive, title=_TITLE))


def test_hosting_verified() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_hosting_verified(
            aws_admin_capability.CallerIdentity(
                account=_STUB_ACCOUNT, identity=_STUB_IDENTITY,
            )
        )

    assert_golden("hosting_verified", render(app, drive, title=_TITLE))
