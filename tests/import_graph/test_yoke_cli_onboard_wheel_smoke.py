"""Product-wheel smoke for minimal ``yoke onboard`` machine setup.

The engine wheel (yoke-core) installs alongside the client; onboarding stays
a pure product-client flow with the engine present but inert.
"""

from __future__ import annotations

import json
from yoke_core.tools.build_release import create_seeded_pip_venv
from pathlib import Path


from onboard_wheel_smoke_support import (
    _fake_external_command_bin,
    _format_result,
    _product_env,
    _registry_server,
    _run,
    _tree_snapshot,
)


def test_onboard_product_wheel_plans_and_writes_machine_config_with_inert_engine(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    venv_dir = tmp_path / "venv"
    create_seeded_pip_venv(venv_dir)
    venv_python = venv_dir / "bin" / "python"
    yoke = venv_dir / "bin" / "yoke"
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(product_wheelhouse),
            "yoke-cli",
            "yoke-core",
        ],
        cwd=tmp_path,
        timeout=180,
    )
    assert yoke.is_file()

    checkout = tmp_path / "external-project"
    checkout.mkdir()
    (checkout / "README.md").write_text("# external\n", encoding="utf-8")
    before_checkout = _tree_snapshot(checkout)

    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    config = machine_home / "config.json"
    token_file = machine_home / "token"
    token_file.write_text("product-token\n", encoding="utf-8")
    gh_marker = tmp_path / "gh-called"
    fake_bin = _fake_external_command_bin(tmp_path, gh_marker)
    env = _product_env(machine_home, venv_dir, extra_path=fake_bin)

    # Engine present: the wheel channel ships yoke-core to every machine.
    _run(
        [
            str(venv_python),
            "-c",
            "import importlib.util; "
            "assert importlib.util.find_spec('yoke_core') is not None",
        ],
        cwd=checkout,
        env=env,
    )

    with _registry_server(expected_token="product-token") as api_url:
        _run_onboard_flow(
            yoke=yoke,
            checkout=checkout,
            env=env,
            config=config,
            token_file=token_file,
            machine_home=machine_home,
            api_url=api_url,
            before_checkout=before_checkout,
            gh_marker=gh_marker,
        )


def _run_onboard_flow(
    *,
    yoke: Path,
    checkout: Path,
    env: dict[str, str],
    config: Path,
    token_file: Path,
    machine_home: Path,
    api_url: str,
    before_checkout: list[tuple[str, str, str]],
    gh_marker: Path,
) -> None:
    help_result = _run([str(yoke), "onboard", "--help"], cwd=checkout, env=env)
    assert "yoke onboard" in help_result.stdout
    assert "source-link" not in help_result.stdout
    assert "source-dev" not in help_result.stdout
    for flag in (
        "--non-interactive --config --env --api-url --token-file --token-stdin "
        "--yes --json --quick --advanced"
    ).split():
        assert flag in help_result.stdout

    plan = _run(
        [
            str(yoke),
            "onboard",
            "--non-interactive",
            "--quick",
            "--config",
            str(config),
            "--env",
            "prod",
            "--api-url",
            api_url,
            "--token-file",
            str(token_file),
            "--json",
        ],
        cwd=checkout,
        env=env,
    )
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["operation"] == "onboard"
    assert plan_payload["mode"] == "quick"
    assert plan_payload["applied"] is False
    assert plan_payload["config_path"] == str(config)
    assert plan_payload["plan"]["active_env"] == "prod"
    assert plan_payload["plan"]["connection"] == {
        "transport": "https",
        "api_url": api_url,
        "credential_source": {
            "kind": "token_file",
            "path": str(machine_home / "secrets" / "prod.token"),
        },
    }
    assert plan_payload["plan"]["token_source"] == {
        "kind": "token_file",
        "path": str(token_file),
    }
    assert "product-token" not in plan.stdout
    assert "source-link" not in plan.stdout
    assert "source-dev" not in plan.stdout
    assert not config.exists()
    assert _tree_snapshot(checkout) == before_checkout
    assert not gh_marker.exists()

    advanced_plan = _run(
        [
            str(yoke),
            "onboard",
            "--non-interactive",
            "--advanced",
            "--config",
            str(machine_home / "advanced.json"),
            "--env",
            "stage",
            "--api-url",
            api_url,
            "--token-file",
            str(token_file),
            "--json",
        ],
        cwd=checkout,
        env=env,
    )
    advanced_payload = json.loads(advanced_plan.stdout)
    assert advanced_payload["mode"] == "advanced"
    assert advanced_payload["applied"] is False
    assert not (machine_home / "advanced.json").exists()

    applied = _run(
        [
            str(yoke),
            "onboard",
            "product-token",
            "--non-interactive",
            "--advanced",
            "--config",
            str(config),
            "--env",
            "prod",
            "--api-url",
            api_url,
            "--yes",
            "--json",
        ],
        cwd=checkout,
        env=env,
    )
    applied_payload = json.loads(applied.stdout)
    assert applied_payload["operation"] == "onboard"
    assert applied_payload["mode"] == "advanced"
    assert applied_payload["applied"] is True
    assert applied_payload["config_path"] == str(config)
    assert "source-link" not in applied.stdout
    assert "source-dev" not in applied.stdout

    config_payload = json.loads(config.read_text("utf-8"))
    assert config_payload["schema_version"] == 1
    assert config_payload["active_env"] == "prod"
    stored_token = machine_home / "secrets" / "prod.token"
    assert config_payload["connections"]["prod"] == {
        "transport": "https",
        "api_url": api_url,
        "credential_source": {
            "kind": "token_file",
            "path": str(stored_token),
        },
    }
    assert stored_token.read_text("utf-8") == "product-token\n"
    assert "product-token" not in applied.stdout
    assert "product-token" not in config.read_text("utf-8")
    assert config.stat().st_mode & 0o077 == 0

    # The stub answers only the registry, so /v1/health 404s: no control plane.
    status = _run(
        [
            str(yoke),
            "status",
            "--config",
            str(config),
            "--env",
            "prod",
            "--json",
        ],
        cwd=checkout,
        env=env,
        check=False,
    )
    assert status.returncode == 1, _format_result(status)
    status_payload = json.loads(status.stdout)
    errors = [i for i in status_payload["issues"] if i["severity"] == "error"]
    assert status_payload["ok"] is False
    assert [issue["code"] for issue in errors] == ["server_unreachable"]
    assert status_payload["connection"]["env"] == "prod"
    assert status_payload["connection"]["transport"] == "https"
    assert status_payload["connection"]["credential_source"]["present"] is True

    assert _tree_snapshot(checkout) == before_checkout
    assert not gh_marker.exists()
