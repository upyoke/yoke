"""`yoke pulumi exec` runs a stack from its checked-in infra/Pulumi.<stack>.yaml."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
import yaml

from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command
from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _init_settings,
)


_STACK = "scratch-file-stack"
_PROVIDER = "awskms://alias/externalwebapp-pulumi-state?region=us-east-1"
_PROJECT_TEXT = (
    "config:\n"
    "  # project-owned values stay exactly as written\n"
    "  scratch:size: small\n"
    "  scratch:enabled: yes\n"
)


def _project(tmp_path: Path, stack_text: str = _PROJECT_TEXT) -> Path:
    root = tmp_path / "project"
    infra = root / "infra"
    (infra / "venv" / "bin").mkdir(parents=True)
    (infra / "Pulumi.yaml").write_text("name: scratch\nruntime: python\n")
    (infra / "__main__.py").write_text("import pulumi\n")
    (infra / "venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    (infra / f"Pulumi.{_STACK}.yaml").write_text(stack_text)
    return root


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


class _Auth:
    token = "github-token"
    repo = "beebauman/externalwebapp"


def _run(root, command, *, calls, seen=None, **kwargs):
    seen = seen if seen is not None else {}

    def child_factory(argv, **child_kwargs):
        cwd = Path(child_kwargs["cwd"])
        calls.append({
            "argv": list(argv),
            "cwd": cwd,
            "stack_text": (cwd / f"Pulumi.{_STACK}.yaml").read_text(),
            "files": sorted(p.name for p in cwd.iterdir()),
            "python_link": (cwd / "venv" / "bin" / "python").is_symlink(),
            "venv_target": (
                (cwd / "venv").resolve() if (cwd / "venv").is_symlink() else None
            ),
            "env": dict(child_kwargs["env"]),
        })
        return _Child(b"preview-ok\n")

    def github_auth_loader(project, *, required_permissions):
        seen["github"] = (project, dict(required_permissions))
        return _Auth()

    return execute_pulumi_command(
        "externalwebapp",
        _STACK,
        command,
        project_root=root,
        settings_loader=lambda project: _init_settings(),
        aws_env_loader=lambda *a, **kw: {"AWS_ACCESS_KEY_ID": "key"},
        github_auth_loader=github_auth_loader,
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
        **kwargs,
    )


def test_preview_runs_from_copy_with_only_yoke_values_added(tmp_path):
    root = _project(tmp_path)
    before = _snapshot(root)
    calls: list[dict] = []

    assert _run(root, ["preview"], calls=calls) == 0

    call = calls[0]
    assert call["argv"] == ["pulumi", "preview", "--stack", _STACK]
    assert root not in call["cwd"].parents
    assert {"Pulumi.yaml", "__main__.py", "venv"} <= set(call["files"])
    assert call["python_link"] is True
    assert _PROJECT_TEXT.splitlines()[1] in call["stack_text"]
    assert "  scratch:enabled: yes\n" in call["stack_text"]
    config = yaml.safe_load(call["stack_text"])["config"]
    added = {key for key in config if key.startswith("yoke:")}
    assert config["scratch:size"] == "small"
    assert set(config) - added == {"scratch:size", "scratch:enabled"}
    assert config["yoke:aws_account_id"] == "657517041453"
    assert config["yoke:kms_key_alias"] == "alias/externalwebapp-pulumi-state"
    assert "secretsprovider" not in yaml.safe_load(call["stack_text"])
    assert call["env"]["PULUMI_BACKEND_URL"] == (
        "s3://externalwebapp-pulumi-state?region=us-east-1"
    )
    assert not any(arg.startswith("--config") for arg in call["argv"])
    assert not any(name.startswith("YOKE_CONFIG") for name in call["env"])
    assert _snapshot(root) == before


def test_checked_in_encryption_lines_are_kept_in_the_copy(tmp_path):
    text = f"secretsprovider: {_PROVIDER}\nencryptedkey: checked-in\n" + _PROJECT_TEXT
    root = _project(tmp_path, text)
    calls: list[dict] = []
    assert _run(root, ["preview"], calls=calls) == 0
    stack = yaml.safe_load(calls[0]["stack_text"])
    assert stack["encryptedkey"] == "checked-in"
    assert stack["secretsprovider"] == _PROVIDER


@pytest.mark.parametrize(
    ("line", "permissions"),
    [
        ("", {"metadata": "read"}),
        ("  yoke:github_access: metadata\n", {"metadata": "read"}),
        (
            "  yoke:github_access: variables\n",
            {"metadata": "read", "actions_variables": "write"},
        ),
    ],
)
def test_github_level_follows_the_file(tmp_path, line, permissions):
    root = _project(tmp_path, _PROJECT_TEXT + line)
    seen: dict = {}
    assert _run(root, ["preview"], calls=[], seen=seen) == 0
    assert seen["github"] == ("externalwebapp", permissions)


def test_unknown_github_level_refuses_before_child(tmp_path):
    root = _project(tmp_path, _PROJECT_TEXT + "  yoke:github_access: admin\n")
    calls: list[dict] = []
    with pytest.raises(PulumiExecError, match="pulumi_github_access_unknown"):
        _run(root, ["preview"], calls=calls)
    assert calls == []


def test_config_flags_stay_refused_on_the_file_path(tmp_path):
    root = _project(tmp_path)
    with pytest.raises(PulumiExecError, match="not allowed"):
        _run(root, ["preview", "--config", "yoke:aws_region=x"], calls=[])


def test_init_accepts_any_stack_name_and_stores_nothing(tmp_path):
    root = _project(tmp_path)
    before = _snapshot(root)
    calls: list[dict] = []

    def child_factory(argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        calls.append({"argv": list(argv), "cwd": cwd})
        stack_path = cwd / f"Pulumi.{_STACK}.yaml"
        stack_path.write_text(
            f"secretsprovider: {_PROVIDER}\nencryptedkey: fresh-key\n"
            + stack_path.read_text()
        )
        return _Child(b"Created stack\n")

    out = StringIO()
    rc = execute_pulumi_command(
        "externalwebapp",
        _STACK,
        ["init", "--secrets-provider", _PROVIDER],
        project_root=root,
        settings_loader=lambda project: _init_settings(),
        aws_env_loader=lambda *a, **kw: {},
        child_factory=child_factory,
        out=out,
        err=StringIO(),
    )

    assert rc == 0
    assert calls[0]["argv"][:4] == ["pulumi", "stack", "init", _STACK]
    assert root not in calls[0]["cwd"].parents
    assert "encryptedkey: fresh-key" in out.getvalue()
    assert f"infra/Pulumi.{_STACK}.yaml" in out.getvalue()
    assert _snapshot(root) == before


def test_init_refuses_a_provider_other_than_the_capability_key(tmp_path):
    root = _project(tmp_path, "secretsprovider: awskms://alias/other\n" + _PROJECT_TEXT)
    with pytest.raises(PulumiExecError, match="pulumi_secrets_provider_mismatch"):
        execute_pulumi_command(
            "externalwebapp",
            _STACK,
            ["init", "--secrets-provider", _PROVIDER],
            project_root=root,
            settings_loader=lambda project: _init_settings(),
            aws_env_loader=lambda *a, **kw: {},
            child_factory=lambda *a, **kw: pytest.fail("child ran"),
            out=StringIO(),
            err=StringIO(),
        )


def test_destroy_runs_on_the_file_path(tmp_path):
    root = _project(tmp_path)
    calls: list[dict] = []
    rc = _run(
        root,
        ["destroy", "--yes", "--non-interactive"],
        calls=calls,
        confirm_destroy=_STACK,
    )
    assert rc == 0
    assert calls[0]["argv"] == [
        "pulumi", "destroy", "--yes", "--non-interactive", "--stack", _STACK,
    ]


def test_stack_rm_runs_on_the_file_path(tmp_path):
    root = _project(tmp_path)
    calls: list[dict] = []
    rc = _run(
        root,
        ["stack", "rm", "--yes"],
        calls=calls,
        confirm_destroy=_STACK,
    )
    assert rc == 0
    assert calls[0]["argv"] == ["pulumi", "stack", "rm", "--yes", "--stack", _STACK]


def test_runner_fleet_level_without_its_capability_refuses_before_child(tmp_path):
    root = _project(tmp_path, _PROJECT_TEXT + "  yoke:github_access: runner_fleet\n")
    calls: list[dict] = []
    with pytest.raises(PulumiExecError, match="pulumi_runner_fleet_values_unavailable"):
        _run(root, ["preview"], calls=calls)
    assert calls == []
