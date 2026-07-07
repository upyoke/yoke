"""Shared harness for the ``yoke onboard`` Textual SVG golden gates.

The gates live in :mod:`test_onboard_wizard_goldens` (PATH / Connect / GitHub)
and :mod:`test_onboard_wizard_goldens_project` (Project / Finish); both import
this module for the render-and-assert machinery, the stubbed host-independent
data, and the catalog<->golden parity scan. Splitting the harness out keeps each
gate module under the authored-file line budget while the goldens stay one flat
``__snapshots__`` tree the parity test owns end to end.

Determinism: Textual renders to a virtual terminal of a fixed size, so the SVG
is identical on macOS, Linux, CI, and EC2. Two build-dependent tokens are
normalized before write/compare — the build version (``{{VERSION}}``) and the
Rich element-id prefix (an adler32 of the rendered glyphs) — so the gate asserts
exact layout + copy + color + glyphs, not the build.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import inspect
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from yoke_cli.config import github_publish
from yoke_cli.config import onboard_project
from yoke_cli.config import path_doctor
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp

SNAPSHOTS_DIR = Path(__file__).resolve().parent / "__snapshots__"
UPDATE = os.environ.get("YOKE_WIZARD_GOLDEN_UPDATE") == "1"

# Pinned virtual-terminal size: wide enough for the stepper rail and the input
# boxes the spec draws, tall enough for the longest screen without scrolling.
TERMINAL_SIZE = (100, 32)

_TERMINAL_ID_RE = re.compile(r"terminal-\d+")
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:\.dev\d+\+g[0-9a-f]+(?:\.d\d+)?)?")


@contextmanager
def golden_color_env():
    """Render approved SVG colors even when the parent shell disables color."""
    previous = os.environ.get("NO_COLOR")
    os.environ.pop("NO_COLOR", None)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("NO_COLOR", None)
        else:
            os.environ["NO_COLOR"] = previous


def _normalize(svg: str) -> str:
    svg = _TERMINAL_ID_RE.sub("terminal-YOKE", svg)
    svg = _VERSION_RE.sub("{{VERSION}}", svg)
    return svg


def assert_golden(name: str, svg: str) -> None:
    path = SNAPSHOTS_DIR / f"{name}.svg"
    captured = _normalize(svg)
    if UPDATE:
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(captured, encoding="utf-8")
        return
    expected = path.read_text(encoding="utf-8")
    assert captured == expected, (
        f"{name}.svg drifted from its blessed golden. Re-bless with "
        f"YOKE_WIZARD_GOLDEN_UPDATE=1 if the change is approved."
    )


# --------------------------------------------------------------------------- #
# Stub data — host-independent so the render is identical everywhere.
# --------------------------------------------------------------------------- #


def _resolution(name: str, path: str | None) -> path_doctor.ToolResolution:
    return path_doctor.ToolResolution(name=name, path=path)


BIN_DIR = "~/.local/bin"
STARTUP = "~/.zprofile"

# PATH diagnosis (needs fix): the current shell sees the tools, a fresh login
# shell does not — the asymmetry the "Add to PATH" screen exists to fix.
DIAGNOSIS_NEEDS_FIX = path_doctor.PathDiagnosis(
    current_shell="zsh",
    tool_bin_dir=BIN_DIR,
    current_on_path=True,
    current_resolved=[
        _resolution("yoke", f"{BIN_DIR}/yoke"),
        _resolution("uv", f"{BIN_DIR}/uv"),
    ],
    startup_file=STARTUP,
    future_adds_bin=False,
    managed_block_present=False,
    future_resolved=[_resolution("yoke", None), _resolution("uv", None)],
    needs_fix=True,
)

# PATH diagnosis (all clear): every shell already finds Yoke.
DIAGNOSIS_ALL_CLEAR = path_doctor.PathDiagnosis(
    current_shell="zsh",
    tool_bin_dir=BIN_DIR,
    current_on_path=True,
    current_resolved=[_resolution("yoke", f"{BIN_DIR}/yoke")],
    startup_file=STARTUP,
    future_adds_bin=True,
    managed_block_present=True,
    future_resolved=[_resolution("yoke", f"{BIN_DIR}/yoke")],
    needs_fix=False,
)

# Fresh-login resolutions after the managed block is written (PATH verified).
VERIFIED_RESOLVED = [
    _resolution("yoke", f"{BIN_DIR}/yoke"),
    _resolution("uv", f"{BIN_DIR}/uv"),
]

OWNERS = [
    github_publish.RepoOwner(login="beebauman", kind="user"),
    github_publish.RepoOwner(login="acme-inc", kind="organization"),
    github_publish.RepoOwner(login="side-project-co", kind="organization"),
]

YOKE_TOKEN_VERIFICATION = {
    "checked": True,
    "ok": True,
    "source": "identity",
    "actor": {"label": "setup-bot"},
    "orgs": [{"name": "Acme Ops", "roles": ["admin"]}],
    "projects": [
        {"slug": "yoke", "roles": ["admin"]},
        {"slug": "buzz", "roles": ["operator"]},
    ],
}

_GITHUB_REPO_DETAILS = [
    {"full_name": "machine-user/private-tool", "private": True,
     "permissions": {"admin": True, "push": True, "pull": True}},
    {"full_name": "octo-org/app", "private": True,
     "permissions": {"admin": False, "push": True, "pull": True}},
    {"full_name": "octo-org/website", "private": False,
     "permissions": {"admin": False, "push": False, "pull": True}},
]


def _capability(**overrides: Any) -> dict[str, Any]:
    base = {
        "kind": "classic", "can_create": True, "create_private": True,
        "can_push_new": True, "can_publish": True,
        "writable": ["machine-user/private-tool", "octo-org/app"],
        "readonly": ["octo-org/website"], "see_private": 2, "see_public": 1,
        "write_probed_count": 0, "write_probe_total": 0,
    }
    return {**base, **overrides}


GITHUB_MACHINE_VERIFICATION = {
    "identity": {"checked": True, "ok": True, "login": "machine-user", "id": 1001},
    "access": {
        "owners": ["machine-user", "octo-org"],
        "repos": [
            "machine-user/private-tool",
            "octo-org/app",
            "octo-org/website",
        ],
        "repo_details": _GITHUB_REPO_DETAILS,
        "repo_count": 3,
    },
    "scopes": ["repo", "workflow"],
    "permissions": {
        "ok": True,
        "mode": "classic",
        "create_repos": {
            "can_create": True,
            "create_private": True,
            "basis": "classic_scope:repo",
        },
        "summary": "classic PAT scopes include repo, workflow",
    },
    "capability": _capability(),
}

GITHUB_FINE_GRAINED_MACHINE_VERIFICATION = {
    "identity": {"checked": True, "ok": True, "login": "machine-user", "id": 1001},
    "access": GITHUB_MACHINE_VERIFICATION["access"],
    "capability": _capability(
        kind="fine_grained", create_private=None, can_push_new=False,
        can_publish=False, writable=["machine-user/private-tool"],
        readonly=["octo-org/website", "octo-org/app"],
        write_probed_count=2, write_probe_total=2,
    ),
    "permissions": {
        "ok": True,
        "mode": "fine_grained_non_mutating",
        "create_repos": {
            "can_create": None,
            "create_private": None,
            "basis": "fine_grained_undetectable",
        },
        "repo": "octo-org/app",
        "write_verified": False,
        "checks": [
            {"key": "actions", "label": "Actions", "status": "read_verified"},
            {
                "key": "administration",
                "label": "Administration",
                "status": "read_verified",
            },
            {"key": "contents", "label": "Contents", "status": "read_verified"},
            {
                "key": "environments",
                "label": "Environments",
                "status": "read_verified",
            },
            {"key": "issues", "label": "Issues", "status": "read_verified"},
            {"key": "metadata", "label": "Metadata", "status": "read_verified"},
            {
                "key": "pull_requests",
                "label": "Pull requests",
                "status": "read_verified",
            },
            {"key": "secrets", "label": "Secrets", "status": "read_verified"},
            {"key": "variables", "label": "Variables", "status": "read_verified"},
            {"key": "workflows", "label": "Workflows", "status": "not_checked"},
        ],
    },
}

# A finish plan with writes in every group (machine / account / project, incl. the post-checkout scaffold + board-art steps) so the review renders every section.
FINISH_PLAN_FULL = {
    "project_mode": onboard_project.PROJECT_MODE_CREATE_REPO,
    "plan": {
        "steps": [
            {"action": "create-or-validate-dir", "target": "~/.yoke"},
            {"action": "store-token-reference", "target": "prod.token"},
            {"action": "set-active-env", "target": "prod"},
            {"action": "project-onboard", "target": "my-project"},
            {"action": "project-create-checkout", "target": "~/code/my-project"},
            {"action": "project-install-scaffold", "target": ""},
            {"action": "project-write-board-art", "target": ""},
        ]
    },
}

FINISH_PLAN_EMPTY: dict[str, Any] = {"plan": {"steps": []}}


def make_app(*, post_install: bool = False, env_name: str = "prod",
             api_url: str = "https://api.upyoke.com",
             token: str | None = "actor-token",
             apply_report: Callable[[dict[str, Any]], Any] | None = None,
             ) -> OnboardWizardApp:
    with golden_color_env():
        return OnboardWizardApp(
            defaults=WizardDefaults(
                config_path="/tmp/cfg.json",
                env_name=env_name,
                api_url=api_url,
                token=token,
                post_install=post_install,
            ),
            apply_report=apply_report or (lambda _kw: {"plan": {"steps": []}}),
        )


def render(app: OnboardWizardApp,
           drive: Callable[[OnboardWizardApp, Any], Awaitable[None]],
           *, title: str) -> str:
    """Run ``app`` to the screen ``drive`` lands on and export it to SVG.

    ``drive`` is awaited inside the pilot context after the front screen mounts;
    it sets up ``app.result`` state and calls the real flow method that renders
    the target view, then the harness pauses so the deferred body swap settles.
    """

    async def scenario() -> str:
        async with app.run_test(size=TERMINAL_SIZE) as pilot:
            await pilot.pause()
            await drive(app, pilot)
            await pilot.pause()
            await pilot.pause()
            return app.export_screenshot(title=title)

    with golden_color_env():
        return asyncio.run(scenario())


# Catalog <-> golden 1:1 parity scan, shared across the gate modules.

# Every gate module that contributes ``test_<screen>`` gates. The parity scan
# reads each one's functions so the committed goldens are checked against the
# full gate set, not one module's slice.
GATE_MODULES = (
    "runtime.api.cli.test_onboard_wizard_goldens",
    "runtime.api.cli.test_onboard_wizard_goldens_project",
    "runtime.api.cli.test_onboard_wizard_goldens_art",
)


def gate_screen_names() -> set[str]:
    """Collect ``<screen>`` from every ``test_<screen>`` gate across the modules.

    The gate name is ``test_`` + the golden stem; the parity test proves that
    mapping is total and injective against the committed ``__snapshots__``.
    """
    import importlib

    names: set[str] = set()
    for mod_name in GATE_MODULES:
        module = importlib.import_module(mod_name)
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            if obj.__module__ != module.__name__:
                continue
            if name == "test_catalog_golden_gate_parity":
                continue
            names.add(name[len("test_"):])
    return names


def assert_catalog_golden_gate_parity() -> None:
    """Goldens and gate tests stand in 1:1 correspondence — provably complete.

    Each committed ``__snapshots__/<screen>.svg`` must have a matching
    ``test_<screen>`` gate, and vice versa. A new screen that adds a golden
    without a gate (or a gate without a golden) fails here, so coverage can never
    silently drift from the approved screen catalog.
    """
    gates = gate_screen_names()
    goldens = {p.stem for p in SNAPSHOTS_DIR.glob("*.svg")}

    missing_goldens = sorted(gates - goldens)
    missing_gates = sorted(goldens - gates)
    assert not missing_goldens, (
        f"gate tests with no committed golden: {missing_goldens} "
        f"(regenerate with YOKE_WIZARD_GOLDEN_UPDATE=1)"
    )
    assert not missing_gates, (
        f"committed goldens with no gate test: {missing_gates} "
        f"(add a test_<screen> gate or remove the stale golden)"
    )
