"""Repository setup handlers for Machine QA fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from yoke_core.domain.machine_qa_fixture_assets import SOURCE_LINK_MODULE
from yoke_core.domain.machine_qa_fixture_constants import SOURCE_SEEDS_PATH
from yoke_core.domain.machine_qa_fixture_runtime import shell_command
from yoke_core.domain.machine_qa_fixture_validation_constants import (
    SOURCE_DEV_ORIGIN,
)


class MachineQaFixtureRepositoryOperations:
    """Build closed local Git and source-install fixture repositories."""

    def _git_checkout(self, parameters: Mapping[str, Any]) -> None:
        path = parameters["path"]
        self._delete(path)
        self._run(shell_command("/bin/mkdir", "-p", path))
        self._upload(f"{path}/README.md", parameters["readme_text"] + "\n")
        if parameters["state"] == "nonempty-folder":
            return
        self._run(
            shell_command(
                "git",
                "-C",
                path,
                "init",
                "-q",
                "-b",
                parameters["default_branch"],
            )
        )
        if parameters.get("origin"):
            self._run(
                shell_command(
                    "git",
                    "-C",
                    path,
                    "remote",
                    "add",
                    "origin",
                    parameters["origin"],
                )
            )
        self._commit_fixture(path)

    def _git_remote(self, parameters: Mapping[str, Any]) -> None:
        seed = f"{SOURCE_SEEDS_PATH}/{parameters['name']}"
        remote = parameters["path"]
        self._delete(seed, remote)
        self._run(shell_command("/bin/mkdir", "-p", seed))
        self._run(
            shell_command(
                "git",
                "-C",
                seed,
                "init",
                "-q",
                "-b",
                parameters["branch"],
            )
        )
        self._upload(f"{seed}/README.md", parameters["name"] + "\n")
        self._commit_fixture(seed)
        self._run(
            shell_command(
                "/bin/mkdir",
                "-p",
                str(PurePosixPath(remote).parent),
            )
        )
        self._run(shell_command("git", "clone", "--bare", "-q", seed, remote))

    def _source_dev_checkout(self, parameters: Mapping[str, Any]) -> None:
        path = parameters["path"]
        self._delete(path)
        state = parameters["state"]
        if state == "fresh":
            return
        self._run(shell_command("/bin/mkdir", "-p", path))
        if state == "non-yoke-folder":
            self._upload(f"{path}/README.md", "not yoke\n")
            return
        self._run(shell_command("git", "-C", path, "init", "-q", "-b", "main"))
        self._upload(
            f"{path}/pyproject.toml",
            '[project]\nname = "yoke"\n',
        )
        self._upload(
            f"{path}/runtime/harness/README.md",
            "source-dev\n",
        )
        self._run(
            shell_command(
                "git",
                "-C",
                path,
                "remote",
                "add",
                "origin",
                parameters["origin"],
            )
        )
        self._commit_fixture(path)

    def _source_dev_remote(self, parameters: Mapping[str, Any]) -> None:
        seed = parameters["seed_path"]
        remote = parameters["remote_path"]
        config = parameters["git_config_path"]
        self._delete(seed, remote, config)
        self._run(shell_command("/bin/mkdir", "-p", seed))
        self._upload_source_tree(seed)
        self._run(
            shell_command(
                "git",
                "-C",
                seed,
                "init",
                "-q",
                "-b",
                parameters["default_branch"],
            )
        )
        self._commit_fixture(seed)
        self._run(
            shell_command(
                "/bin/mkdir",
                "-p",
                str(PurePosixPath(remote).parent),
            )
        )
        self._run(shell_command("git", "clone", "--bare", "-q", seed, remote))
        self._run(
            shell_command(
                "git",
                "config",
                "--file",
                config,
                "protocol.file.allow",
                "always",
            )
        )
        self._run(
            shell_command(
                "git",
                "config",
                "--file",
                config,
                f"url.{parameters['remote_url']}.insteadOf",
                SOURCE_DEV_ORIGIN,
            )
        )

    def _upload_source_tree(self, root: str) -> None:
        self._upload(
            f"{root}/pyproject.toml",
            '[project]\nname = "yoke"\n',
        )
        for package in (
            "yoke-contracts",
            "yoke-core",
            "yoke-cli",
            "yoke-harness",
        ):
            package_root = f"{root}/packages/{package}"
            self._upload(
                f"{package_root}/pyproject.toml",
                f'[project]\nname = "{package}"\n',
            )
            self._upload(f"{package_root}/src/.gitkeep", "")
        module_root = f"{root}/packages/yoke-core/src/yoke_core"
        self._upload(f"{module_root}/__init__.py", "")
        self._upload(f"{module_root}/domain/__init__.py", "")
        self._upload(
            f"{module_root}/domain/project_install_source_link.py",
            SOURCE_LINK_MODULE,
        )
        for relative in (
            "runtime/harness/claude/agents/.gitkeep",
            "runtime/harness/claude/agents/references/.gitkeep",
            "runtime/harness/codex/.gitkeep",
            "runtime/harness/cursor/hooks.json",
        ):
            content = (
                '{"version": 1, "hooks": {}}\n'
                if relative.endswith("cursor/hooks.json")
                else ""
            )
            self._upload(f"{root}/{relative}", content)
        self._upload(
            f"{root}/.agents/skills/yoke/SKILL.md",
            "# Yoke skill\n",
        )
        self._upload(
            f"{root}/.agents/tester-browser.md",
            "# Tester browser\n",
        )

    def _commit_fixture(self, path: str) -> None:
        self._run(shell_command("git", "-C", path, "add", "."))
        self._run(
            shell_command(
                "git",
                "-C",
                path,
                "-c",
                "user.email=recipe@example.invalid",
                "-c",
                "user.name=Recipe",
                "commit",
                "-q",
                "-m",
                "init",
            )
        )

    def _project_registrations(
        self,
        parameters: Mapping[str, Any],
    ) -> None:
        config_path = self._resolve_path(parameters["config_path"])
        for project in parameters["projects"]:
            path = project["path"]
            self._delete(path)
            self._run(shell_command("/bin/mkdir", "-p", path))
            self._run(
                shell_command(
                    self._yoke_bin(),
                    "project",
                    "register",
                    path,
                    "--project-id",
                    project["project_id"],
                    "--config",
                    config_path,
                )
            )


__all__ = ["MachineQaFixtureRepositoryOperations"]
