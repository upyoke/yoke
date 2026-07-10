"""Exact-byte SVG golden gates — PATH, Connect, and GitHub wizard screens.

Each ``APPROVED`` Textual screen in the cold-start spec has one committed SVG
golden under ``__snapshots__/<screen>.svg``. A gate renders the real
:class:`~yoke_cli.config.onboard_wizard_app.OnboardWizardApp` at a pinned
virtual-terminal size, drives it to the target screen with stubbed data, exports
the screen to SVG, normalizes the build-dependent tokens, and asserts the bytes
match the committed golden. Because Textual renders to a virtual terminal of a
fixed size, the bytes are identical on macOS, Linux, CI, and EC2, so the gate
verifies the exact approved render anywhere.

The operator blesses each golden once — it IS their approved render. Regenerate
after an approved copy change:

    YOKE_WIZARD_GOLDEN_UPDATE=1 pytest runtime/api/cli/

The Project / Finish gates live in :mod:`test_onboard_wizard_goldens_project`;
the shared harness and the catalog<->golden parity scan live in
:mod:`onboard_wizard_golden_support`. The parity meta-test below covers the
goldens from both gate modules.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_golden_support import (  # noqa: E402
    DIAGNOSIS_ALL_CLEAR,
    DIAGNOSIS_NEEDS_FIX,
    STARTUP,
    YOKE_TOKEN_VERIFICATION,
    VERIFIED_RESOLVED,
    assert_catalog_golden_gate_parity,
    assert_golden,
    make_app,
    render,
)
from yoke_cli.config import onboard_wizard_path  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import path_doctor  # noqa: E402
from yoke_cli.config.onboard_destinations import (  # noqa: E402
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
)
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402
from yoke_cli.config.onboard_wizard_state import _View  # noqa: E402

_BIN_DIR = "~/.local/bin"


# --------------------------------------------------------------------------- #
# PATH step (batch 1 + 2)
# --------------------------------------------------------------------------- #


def test_path_install_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin the displayed version so this golden's layout is deterministic and
    # machine-independent. _yoke_version() reads importlib.metadata, which a
    # co-located product-boundary test (simulating a missing package) can make
    # raise — yielding a different-length fallback string that shifts the SVG
    # layout coordinates even though the version text normalizes to {{VERSION}}.
    monkeypatch.setattr(onboard_wizard_path, "_yoke_version", lambda: "0.1.0")
    app = make_app(post_install=True)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_install_summary()

    assert_golden("path_install_summary", render(app, drive, title="yoke onboard · Install"))


def test_path_diagnosis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: DIAGNOSIS_NEEDS_FIX)
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_path_diagnosis()

    assert_golden("path_diagnosis", render(app, drive, title="yoke onboard · Install"))


def test_path_diagnosis_allclear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: DIAGNOSIS_ALL_CLEAR)
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_path_diagnosis()

    assert_golden("path_diagnosis_allclear", render(app, drive, title="yoke onboard · Install"))


def test_path_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    # This is a render golden, not a shell-probe test. Pin the complete domain
    # result so the SVG cannot inherit PATH, startup-file, or subprocess state
    # from the host or an earlier test in the same xdist worker.
    diagnosis = replace(
        DIAGNOSIS_NEEDS_FIX,
        tool_bin_dir=_BIN_DIR,
        startup_file=STARTUP,
        ssh_startup_file="~/.zshenv",
        ssh_needs_fix=True,
    )
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: diagnosis)
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_path_preview()

    assert_golden("path_preview", render(app, drive, title="yoke onboard · Install"))


def test_path_verified() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_path_verified(STARTUP, VERIFIED_RESOLVED)

    assert_golden("path_verified", render(app, drive, title="yoke onboard · Install"))


# --------------------------------------------------------------------------- #
# Account step: destination picker + per-destination sign-in lanes
# --------------------------------------------------------------------------- #


def test_connect_destination_picker() -> None:
    app = make_app(api_url="")  # nothing stored: the picker opens the step

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._start_connect()

    assert_golden(
        "connect_destination_picker",
        render(app, drive, title="yoke onboard · Account"),
    )


def test_connect_local_universe() -> None:
    app = make_app(api_url="")

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._after_destination_select(DESTINATION_LOCAL)

    assert_golden(
        "connect_local_universe",
        render(app, drive, title="yoke onboard · Universe"),
    )


def test_connect_env_select() -> None:
    app = make_app(api_url="")  # hosted pick with nothing stored: env select

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._after_destination_select(DESTINATION_HOSTED)

    assert_golden("connect_env_select", render(app, drive, title="yoke onboard · Account"))


def test_connect_server_url_input() -> None:
    app = make_app(api_url="")

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._after_destination_select(DESTINATION_SERVER)

    assert_golden(
        "connect_server_url_input",
        render(app, drive, title="yoke onboard · Account"),
    )


def test_connect_token_method() -> None:
    app = make_app(token=None)  # no token forces the token-method screen

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_token_source()

    assert_golden("connect_token_method", render(app, drive, title="yoke onboard · Account"))


def test_connect_token_paste() -> None:
    app = make_app(token=None)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._after_token_source("prompt")

    assert_golden("connect_token_paste", render(app, drive, title="yoke onboard · Account"))


def test_connect_token_file_input() -> None:
    app = make_app(token=None)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._after_token_source("file")

    assert_golden("connect_token_file_input", render(app, drive, title="yoke onboard · Account"))


def test_connect_token_verified() -> None:
    app = make_app(token=None)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_yoke_verify_success(YOKE_TOKEN_VERIFICATION)

    assert_golden("connect_token_verified", render(app, drive, title="yoke onboard · Account"))


def test_connect_token_error() -> None:
    app = make_app(token=None)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_yoke_verify_error(
            "Yoke token check failed: https://api.upyoke.com/v1/auth/identity "
            "returned HTTP 401: API token is unknown",
            "prompt",
        )

    assert_golden("connect_token_error", render(app, drive, title="yoke onboard · Account"))


# --------------------------------------------------------------------------- #
# GitHub step (batch 3)
# --------------------------------------------------------------------------- #


def test_github_connect_account() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_machine_github()

    assert_golden("github_connect_account", render(app, drive, title="yoke onboard · GitHub"))


def test_github_app_connect_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        def hold_checking_screen(**kwargs: Any) -> None:
            a._checking = True
            a._goto(_View(
                kwargs["step"],
                lambda: steps.checking_body(
                    kwargs["title"],
                    kwargs["message"],
                    kwargs["detail_lines"],
                ),
            ))

        monkeypatch.setattr(a, "_run_checking", hold_checking_screen)
        a._on_machine_github("connect")

    assert_golden("github_app_connect_pending", render(app, drive, title="yoke onboard · GitHub"))


def test_github_app_connect_error() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_machine_github_error(
            "GitHub check failed: https://api.github.com/user returned HTTP 401"
        )

    assert_golden("github_app_connect_error", render(app, drive, title="yoke onboard · GitHub"))


# --------------------------------------------------------------------------- #
# Catalog <-> golden 1:1 parity meta-test (covers both gate modules).
# --------------------------------------------------------------------------- #


def test_catalog_golden_gate_parity() -> None:
    assert_catalog_golden_gate_parity()
