"""Product-wheel smoke for ``yoke project install`` copy mode.

The engine wheel (yoke-core) installs alongside the client; install,
refresh, and uninstall stay pure product-client flows with the engine
present but inert.
"""

from pathlib import Path
import json

from yoke_core.tools.build_release import create_seeded_pip_venv
from runtime.api.fixtures.project_install_wheel_smoke import (
    _assert_installed,
    _BundleServer,
    _bundle,
    _product_env,
    _run,
    _write_https_config,
)


def test_project_install_product_wheel_uses_https_bundle_with_inert_engine(
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
    _run(["git", "init", "-b", "trunk"], cwd=checkout)

    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    token_file = machine_home / "token"
    token_file.write_text("product-token\n", encoding="utf-8")
    env = _product_env(machine_home, venv_dir)

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

    with _BundleServer(_bundle()) as server:
        config = _write_https_config(machine_home, token_file, server.url)
        install_help = _run(
            [str(yoke), "project", "install", "--help"],
            cwd=checkout,
            env=env,
        )
        assert "--source-link" not in install_help.stdout
        assert "source-link" not in install_help.stdout
        assert "source-dev" not in install_help.stdout

        install = _run(
            [
                str(yoke),
                "project",
                "install",
                str(checkout),
                "--project-id",
                "7",
                "--config",
                str(config),
                "--no-commit",
            ],
            cwd=checkout,
            env=env,
            timeout=90,
        )
        install_payload = json.loads(install.stdout)
        assert install_payload["operation"] == "install"
        assert install_payload["mode"] == "copy"
        assert install_payload["source"] == server.url
        assert install_payload["machine_config_newly_registered"] is True
        assert "source-link" not in install.stdout
        assert "source-dev" not in install.stdout
        assert "source-link" not in install.stderr
        assert "source-dev" not in install.stderr
        assert server.requests == [
            ("/v1/projects/7/install-bundle", "Bearer product-token")
        ]

        _assert_installed(checkout, config)

        (checkout / ".yoke/lint-config").write_text(
            "lint_main_commit=allow\n", encoding="utf-8"
        )
        server.bundle = _bundle(
            files=[
                {
                    "path": ".codex/skills/yoke/idea/SKILL.md",
                    "content": "# idea codex\n",
                }
            ]
        )
        refresh = _run(
            [
                str(yoke),
                "project",
                "refresh",
                str(checkout),
                "--config",
                str(config),
                "--force",
                "--no-commit",
            ],
            cwd=checkout,
            env=env,
            timeout=90,
        )
        assert sorted(json.loads(refresh.stdout)["files_pruned"]) == [
            ".claude/agents/yoke-engineer.md",
            ".claude/skills/yoke/idea/SKILL.md",
        ]
        assert not (checkout / ".claude/skills/yoke/idea/SKILL.md").exists()
        assert (checkout / ".yoke/lint-config").read_text(
            encoding="utf-8"
        ) == "lint_main_commit=allow\n"

        # Install and refresh deliberately used --no-commit; uninstall owns
        # a removal commit and requires the operator's starting tree clean.
        _run(["git", "add", "."], cwd=checkout, env=env)
        _run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.name=Smoke",
                "-c",
                "user.email=smoke@example.test",
                "commit",
                "-m",
                "Install Yoke",
            ],
            cwd=checkout,
            env=env,
        )

        uninstall = _run(
            [
                str(yoke),
                "project",
                "uninstall",
                str(checkout),
                "--config",
                str(config),
            ],
            cwd=checkout,
            env=env,
            timeout=90,
        )
        payload = json.loads(uninstall.stdout)
        assert len(server.function_requests) == 1
        request = server.function_requests[0]
        assert request["function"] == "projects.get"
        assert request["payload"] == {"project": "7", "field": "default_branch"}
        assert payload["commit"]
        assert not _run(["git", "status", "--porcelain"], cwd=checkout).stdout.strip()
        assert payload["files_removed"] == [".codex/skills/yoke/idea/SKILL.md"]
        assert payload["contract_files_preserved_modified"] == [".yoke/lint-config"]
        assert payload["strategy_files_preserved"] == [".yoke/strategy/MISSION.md"]
        assert payload["git_hooks_removed"] == [
            "pre-commit",
            "post-commit",
            "pre-merge-commit",
        ]
        assert not (checkout / ".yoke/install-manifest.json").exists()
        assert not (checkout / ".codex/hooks.json").exists()
        assert not (checkout / ".claude/settings.json").exists()
        assert (checkout / ".yoke/lint-config").is_file()
        assert (checkout / ".yoke/strategy/MISSION.md").is_file()
