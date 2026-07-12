"""Shared pilot scaffolding for the ``yoke onboard`` wizard flow suites.

The flow tests split across sibling modules (core flow, back-navigation) to stay
under the per-file line limit; this module holds the fixtures, the build_report
spy, the app factory, and the literal-key typing helper they all reuse.
``build_report`` is spied at the wizard boundary so no scenario performs a real
machine or Yoke core database write, and the PATH doctor is stubbed so no
scenario spawns a login shell.
"""

from __future__ import annotations

from yoke_cli.config import path_doctor
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp


def all_clear_diagnosis() -> path_doctor.PathDiagnosis:
    resolved = [path_doctor.ToolResolution(t, f"/bin/{t}") for t in path_doctor.TOOLS]
    return path_doctor.PathDiagnosis(
        current_shell="zsh",
        tool_bin_dir="/home/u/.local/bin",
        current_on_path=True,
        current_resolved=resolved,
        startup_file="/home/u/.zprofile",
        future_adds_bin=True,
        managed_block_present=True,
        future_resolved=resolved,
        needs_fix=False,
        ssh_startup_file="/home/u/.zshenv",
        ssh_adds_bin=True,
        ssh_managed_block_present=True,
        ssh_resolved=resolved,
        ssh_needs_fix=False,
    )


def stub_path_doctor(monkeypatch) -> None:
    """Keep the PATH step deterministic: no subprocess, nothing needs fixing.

    The flow tests drive Connect onward, so the PATH step renders its all-clear
    "Continue" row and never spawns a login shell.
    """
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: all_clear_diagnosis())
    monkeypatch.setattr(
        path_doctor, "verify_fresh_login",
        lambda shell=None: all_clear_diagnosis().future_resolved,
    )
    monkeypatch.setattr(
        path_doctor, "verify_ssh_command",
        lambda shell=None: all_clear_diagnosis().ssh_resolved,
    )
    stub_token_verifiers(monkeypatch)
    stub_board_art(monkeypatch)
    # Flow scenarios type host-independent fictional folder paths; accept them so
    # the real filesystem validators (covered by their own unit suite) don't trip.
    stub_folder_validators(monkeypatch)
    # The Review pre-flight runs network probes (token still valid, repo name
    # free); stub them clear so flow scenarios stay offline. The pre-flight's real
    # behavior is covered by its own unit + flow suite.
    stub_preflight_clear(monkeypatch)


def stub_board_art(monkeypatch) -> None:
    """Keep the board-art step's apply side-effects offline: the real run writes
    ``.yoke/board-art`` into the checkout and rebuilds the board, but flow
    scenarios apply against a spy report with no real checkout, so the write and
    rebuild are no-ops here."""
    from yoke_cli.config import onboard_wizard_board_art

    monkeypatch.setattr(onboard_wizard_board_art, "write_board_art", lambda *a, **k: None)
    monkeypatch.setattr(onboard_wizard_board_art, "rebuild_board", lambda *a, **k: None)


def stub_token_verifiers(monkeypatch) -> None:
    """Keep wizard authorization confirmation screens deterministic and offline."""
    from yoke_cli.config import existing_project_lookup
    from yoke_cli.config import onboard_wizard_flow_connect
    from yoke_cli.config import onboard_wizard_flow_github

    monkeypatch.setattr(
        onboard_wizard_flow_connect,
        "verify_yoke_token",
        lambda api_url, token: {
            "checked": True,
            "ok": True,
            "status": "verified",
            "orgs": [{"name": "Default Org", "roles": ["admin"]}],
            "projects": [{"slug": "yoke", "roles": ["owner"]}],
            "actor": {"label": "test-actor"},
        },
    )
    github_report = {
        "ok": True,
        "ready": True,
        "configured": True,
        "state": "connected",
        "api_url": "https://api.github.com",
        "app": {"slug": "yoke-product", "app_id": 123, "client_id": "Iv1.test"},
        "identity": {"checked": True, "ok": True, "login": "machine-user"},
        "access": {
            "owners": ["machine-user", "octo-org"],
            "repos": ["machine-user/private-tool", "octo-org/app"],
            "repo_count": 2,
            "installations": [
                {
                    "installation_id": 1,
                    "account_login": "machine-user",
                    "repository_selection": "selected",
                    "suspended": False,
                },
                {
                    "installation_id": 2,
                    "account_login": "octo-org",
                    "repository_selection": "all",
                    "suspended": False,
                },
            ],
        },
        "permissions": {
            "ok": True,
            "usable": True,
            "mode": "github_app_installation",
        },
        "issues": [],
    }
    monkeypatch.setattr(
        onboard_wizard_flow_github.github_machine,
        "connect",
        lambda **_kwargs: dict(github_report),
    )
    monkeypatch.setattr(
        onboard_wizard_flow_github.github_machine,
        "status",
        lambda **_kwargs: dict(github_report),
    )
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_github_repo",
        lambda **_: None,
    )


def stub_preflight_clear(monkeypatch) -> None:
    """Make the Review pre-flight report no problems (offline, deterministic).

    Stubbed at the wizard's seam so flow scenarios that reach the Review screen
    never run the network probes (token verify / repo-exists). Scenarios that
    exercise the pre-flight itself stub this differently or drive the pure
    ``preflight`` helper directly.
    """
    from yoke_cli.config.onboard_wizard_flow import WizardFlow
    from yoke_cli.config.onboard_preflight import PreflightResult

    monkeypatch.setattr(
        WizardFlow, "_review_preflight",
        lambda self: PreflightResult(problems=[], notes=[]),
    )


def stub_folder_validators(monkeypatch) -> None:
    """Accept any folder path so flow scenarios can type fictional paths.

    The create/clone folder steps validate the real filesystem (a path must be
    empty/new with a writable parent). Flow scenarios that exercise downstream
    routing type host-independent fictional paths (``/home/code/widget``), so the
    filesystem validators are no-oped here. The validators' real behavior is
    covered directly by the validator unit suite, not these flow scenarios.
    """
    from yoke_cli.config import onboard_input_validation as validation

    monkeypatch.setattr(validation, "validate_create_target_folder", lambda _p: None)
    monkeypatch.setattr(validation, "validate_clone_target_folder", lambda _p: None)


def stub_source_branch(
    monkeypatch, branch: str | None = "main", *, reachable: bool = True
) -> None:
    """Keep the clone-URL step's git probes offline and deterministic.

    The clone-URL step runs ``git ls-remote`` against the pasted URL twice over:
    once during inline validation (reject an unreachable source) and once for
    branch detection (record the source's real default branch). Flow scenarios
    use fictional URLs, so both transport probes are stubbed — ``branch`` is the
    detected default (``None`` = no parseable HEAD) and ``reachable`` is whether
    the URL passes the inline reachability check. No scenario shells out to git.
    """
    from yoke_cli.config import project_git_probe, project_git_transport

    monkeypatch.setattr(
        project_git_transport,
        "remote_probe",
        lambda url, token=None, github_web_url=None: project_git_probe.GitRemoteProbe(
            reachable,
            default_branch=branch if reachable else None,
            failure_kind=None if reachable else project_git_probe.FAILURE_OTHER,
        ),
    )

    monkeypatch.setattr(
        project_git_transport, "remote_default_branch",
        lambda url, token=None, github_web_url=None: branch,
    )
    monkeypatch.setattr(
        project_git_transport, "remote_is_reachable",
        lambda url, token=None, github_web_url=None: reachable,
    )


async def advance_past_path(pilot) -> None:
    """From on_mount's PATH-diagnosis view, take the single Continue row."""
    await pilot.press("enter")  # path: continue (all clear)


async def complete_board_art(pilot) -> None:
    """Walk the board-art step from its intro to the Finish/review screen.

    Real-project onboarding now routes project -> board art -> Finish, and the
    gallery's Continue needs at least one saved header. This takes the shortest
    valid path: accept the default map, generate one ASCII header, save it, and
    continue. Scenarios that don't care about art call this once where they used
    to land on Finish directly.
    """
    await pilot.press("enter")  # intro: "Let's design it"
    await pilot.press("enter")  # map: "Looks good — continue"
    await pilot.press("enter")  # style: ASCII (first row)
    await pilot.press("enter")  # preview: "Save to board"
    await pilot.press("down")   # gallery: move to "Continue"
    await pilot.press("enter")  # gallery: "Continue" -> Finish


class Spy:
    """Records every build_report kwargs dict and returns a canned plan dict."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, kwargs: dict, progress=None) -> dict:
        self.calls.append(kwargs)
        # Drive the live-progress seam so flow scenarios exercise the Applying
        # screen path; the canned plan has two steps.
        if progress is not None and kwargs.get("apply"):
            for action, target in (
                ("create-or-validate-dir", "/home/.yoke"),
                ("set-active-env", kwargs["env_name"]),
            ):
                progress(action, target, "running")
                progress(action, target, "done")
        return {
            "operation": "onboard",
            "mode": kwargs["mode"],
            "project_mode": kwargs["project_mode"],
            "applied": bool(kwargs["apply"]),
            "config_path": kwargs["config_path"],
            "plan": {"steps": [
                {"action": "create-or-validate-dir", "target": "/home/.yoke"},
                {"action": "set-active-env", "target": kwargs["env_name"]},
            ]},
            "identity": {"checked": False, "ok": None},
            "next_steps": [],
        }

    @property
    def applied(self) -> dict | None:
        for call in self.calls:
            if call["apply"]:
                return call
        return None


def make_app(defaults: WizardDefaults | None = None) -> tuple[OnboardWizardApp, Spy]:
    spy = Spy()
    app = OnboardWizardApp(
        defaults=defaults or WizardDefaults(
            config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
            token="actor-token",
        ),
        apply_report=spy,
    )
    return app, spy


_KEY_NAMES = {
    "/": "slash", "-": "minus", ".": "full_stop", ":": "colon",
    "@": "at", "_": "underscore",
}


def literal_key(char: str) -> str:
    return _KEY_NAMES.get(char, char)


async def type_text(pilot, text: str) -> None:
    for char in text:
        await pilot.press(literal_key(char))
