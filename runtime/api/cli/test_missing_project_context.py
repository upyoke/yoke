"""Client selection refuses unmapped folders and forwards caller project context."""

from types import SimpleNamespace

import pytest

from yoke_contracts.project_defaults import MissingProjectError
from yoke_cli.config import project_selection


def test_client_refusal_uses_its_own_authority(monkeypatch, tmp_path):
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda _p: None
    )
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.ensure_handlers_loaded", lambda: None
    )
    seen = []

    def dispatch(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(success=True, result={"rows": [{"slug": "mine"}]})

    monkeypatch.setattr("yoke_cli.transport.dispatcher.call_dispatcher", dispatch)
    with pytest.raises(MissingProjectError, match="Accessible projects: mine"):
        project_selection.required_project_context(directory=tmp_path)
    assert seen[0]["function_id"] == "projects.list"
    assert seen[0]["payload"] == {"fields": ["id", "slug"]}


def test_browser_profile_refuses_unmapped_directory(monkeypatch, tmp_path):
    from yoke_cli.config import browser_profile

    def refuse(*_args, **_kwargs):
        raise MissingProjectError(
            "project_required: no project given — pass --project P"
        )

    monkeypatch.setattr(browser_profile, "required_project_context", refuse)
    with pytest.raises(MissingProjectError, match="project_required"):
        browser_profile.profile_project_key(directory=tmp_path)


@pytest.mark.parametrize(
    "explicit,env,bound,expected",
    [
        ("explicit", "env", "42", "explicit"),
        (None, "env", "42", "env"),
        (None, "", "42", "42"),
    ],
)
def test_dash_forwards_the_callers_selection(
    monkeypatch, explicit, env, bound, expected
):
    from yoke_cli.commands.adapters import dash_file
    from yoke_cli.commands import _helpers

    monkeypatch.setenv("YOKE_PROJECT", env)
    monkeypatch.setattr(
        "yoke_cli.config.checkout_context.resolve_repo_root_from_cwd", lambda: "/mapped"
    )
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.project_id", lambda _p: int(bound)
    )
    monkeypatch.setattr(
        dash_file, "client_project_context", _helpers.client_project_context
    )
    seen = []
    monkeypatch.setattr(
        dash_file, "dispatch_and_emit", lambda **kw: seen.append(kw) or 0
    )
    args = ["test", "instruction", "--execution-instructions-considered"]
    if explicit:
        args += ["--project", explicit]
    assert dash_file.dash_file(args) == 0
    assert seen[0]["payload"]["project"] == expected


@pytest.mark.parametrize(
    "operation,args",
    [
        (
            "qa_browser_screenshot",
            ["https://example.test", "--output", "/tmp/proof.png"],
        ),
        (
            "qa_browser_step",
            ["--base-url", "https://example.test", "--step-json", "{}"],
        ),
        ("qa_browser_status", ["--json"]),
        ("qa_browser_setup", ["--dry-run", "--json"]),
    ],
)
def test_browser_commands_refuse_before_daemon_work(
    monkeypatch, capsys, operation, args
):
    from yoke_cli.commands import qa_browser, qa_browser_lifecycle

    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda _p: None
    )
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.ensure_handlers_loaded", lambda: None
    )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_kw: SimpleNamespace(
            success=True, result={"rows": [{"slug": "mine"}]}
        ),
    )
    monkeypatch.setattr(
        "yoke_harness.browser_runtime_home.ensure_materialized",
        lambda: pytest.fail("missing project must not materialize the browser"),
    )
    module = qa_browser if hasattr(qa_browser, operation) else qa_browser_lifecycle
    assert getattr(module, operation)(args) == 2
    output = capsys.readouterr()
    assert "project_required" in output.out + output.err
    assert "Accessible projects: mine" in output.out + output.err
    assert "Traceback" not in output.out + output.err


def test_browser_client_no_args_does_not_resolve_project(monkeypatch):
    from yoke_core.domain.browser_client import main

    monkeypatch.setattr("sys.argv", ["browser_client"])
    monkeypatch.setattr(
        "yoke_cli.config.browser_profile.required_project_context",
        lambda *_a, **_kw: pytest.fail("help must not resolve a project"),
    )
    assert main() == 3


def test_browser_client_missing_project_returns_named_refusal(monkeypatch, capsys):
    from yoke_core.domain.browser_client import main

    monkeypatch.setattr("sys.argv", ["browser_client", "daemon", "status"])

    def refuse(*_a, **_kw):
        raise MissingProjectError(
            "project_required: no project given — pass --project P. Accessible projects: mine."
        )

    monkeypatch.setattr(
        "yoke_cli.config.browser_profile.required_project_context", refuse
    )
    assert main() == 2
    assert "Accessible projects: mine" in capsys.readouterr().err
