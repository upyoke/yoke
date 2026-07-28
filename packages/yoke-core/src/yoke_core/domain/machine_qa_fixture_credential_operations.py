"""Credential fixture mutation and opaque restoration handlers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from yoke_contracts.machine_qa_execution import HOST_TEST_COMMAND

from yoke_core.domain.machine_qa_fixture_assets import FIXTURE_ROOT
from yoke_core.domain.machine_qa_fixture_runtime import (
    AuthStateRestore,
    RemoteFixtureFailure,
    TokenRestore,
    shell_command,
)
from yoke_core.domain.machine_qa_fixture_validation import (
    MachineQaFixtureOperationError,
)


_SYNTHETIC_VALID_TOKEN = "test-token-for-" + "live-recipe"
_SYNTHETIC_INVALID_TOKEN = "not-a-real-" + "yoke-token"
_INTERNAL_RESTORE_ROOT = f"{FIXTURE_ROOT}/restores"


class MachineQaFixtureCredentialOperations:
    """Temporarily mutate credential state and restore it without reading it."""

    def _token_file(self, parameters: Mapping[str, Any]) -> None:
        target = self._resolve_path(parameters["path"])
        state = parameters["state"]
        if parameters["restore_after"]:
            self._prepare_token_restore(target)
        if state == "missing":
            self._delete(target)
            return
        if state == "empty":
            self._upload(target, "", mode=0o600)
            return
        if state == "synthetic-valid":
            self._upload(
                target,
                _SYNTHETIC_VALID_TOKEN + "\n",
                mode=0o600,
            )
            return
        if state == "synthetic-invalid":
            self._upload(
                target,
                _SYNTHETIC_INVALID_TOKEN + "\n",
                mode=0o600,
            )
            return
        source = self._resolve_path(parameters["source_path"])
        self._run(
            shell_command(
                "/bin/mkdir",
                "-p",
                str(PurePosixPath(target).parent),
            )
        )
        self._run(shell_command("/bin/cp", source, target))
        self._run(shell_command("/bin/chmod", "600", target))

    def _prepare_token_restore(self, target: str) -> None:
        if any(
            isinstance(item, TokenRestore) and item.target_path == target
            for item in self._restores
        ):
            raise MachineQaFixtureOperationError("token restoration is already pending")
        backup = f"{_INTERNAL_RESTORE_ROOT}/stage.token"
        self._delete(backup)
        self._run(shell_command("/bin/mkdir", "-p", _INTERNAL_RESTORE_ROOT))
        returncode = self._invoke(shell_command(HOST_TEST_COMMAND, "-f", target))
        if returncode not in (0, 1):
            raise RemoteFixtureFailure
        restore = TokenRestore(
            target_path=target,
            backup_path=backup,
            existed=returncode == 0,
        )
        self._restores.append(restore)
        if restore.existed:
            self._run(shell_command("/bin/cp", target, backup))
            self._run(shell_command("/bin/chmod", "600", backup))
        restore.restore_required = True

    def _restore_token(self, restore: TokenRestore) -> None:
        if not restore.restore_required:
            self._delete(restore.backup_path)
            return
        if restore.existed:
            self._run(
                shell_command(
                    "/bin/mkdir",
                    "-p",
                    str(PurePosixPath(restore.target_path).parent),
                )
            )
            self._run(
                shell_command(
                    "/bin/cp",
                    restore.backup_path,
                    restore.target_path,
                )
            )
            self._run(shell_command("/bin/chmod", "600", restore.target_path))
        else:
            self._delete(restore.target_path)
        self._delete(restore.backup_path)

    def _yoke_auth_clear(self, _parameters: Mapping[str, Any]) -> None:
        restore = self._prepare_auth_restore()
        self._delete(restore.config_path, restore.secrets_path)

    def _prepare_auth_restore(self) -> AuthStateRestore:
        config_path = f"{self.home}/.yoke/config.json"
        secrets_path = f"{self.home}/.yoke/secrets"
        backup_root = f"{_INTERNAL_RESTORE_ROOT}/auth-{len(self._restores)}"
        config_status = self._invoke(shell_command(HOST_TEST_COMMAND, "-f", config_path))
        secrets_status = self._invoke(
            shell_command(HOST_TEST_COMMAND, "-d", secrets_path)
        )
        if config_status not in (0, 1) or secrets_status not in (0, 1):
            raise RemoteFixtureFailure
        self._delete(backup_root)
        self._run(shell_command("/bin/mkdir", "-p", backup_root))
        self._run(shell_command("/bin/chmod", "700", backup_root))
        restore = AuthStateRestore(
            config_path=config_path,
            secrets_path=secrets_path,
            backup_root=backup_root,
            config_existed=config_status == 0,
            secrets_existed=secrets_status == 0,
        )
        self._restores.append(restore)
        if restore.config_existed:
            self._run(
                shell_command(
                    "/bin/cp",
                    "-p",
                    config_path,
                    f"{backup_root}/config.json",
                )
            )
        if restore.secrets_existed:
            self._run(
                shell_command(
                    "/bin/cp",
                    "-R",
                    "-p",
                    secrets_path,
                    f"{backup_root}/secrets",
                )
            )
        restore.restore_required = True
        return restore

    def _restore_auth_state(self, restore: AuthStateRestore) -> None:
        if not restore.restore_required:
            self._delete(restore.backup_root)
            return
        self._delete(restore.config_path, restore.secrets_path)
        self._run(
            shell_command(
                "/bin/mkdir",
                "-p",
                str(PurePosixPath(restore.config_path).parent),
            )
        )
        if restore.config_existed:
            self._run(
                shell_command(
                    "/bin/cp",
                    "-p",
                    f"{restore.backup_root}/config.json",
                    restore.config_path,
                )
            )
        if restore.secrets_existed:
            self._run(
                shell_command(
                    "/bin/cp",
                    "-R",
                    "-p",
                    f"{restore.backup_root}/secrets",
                    restore.secrets_path,
                )
            )
        self._delete(restore.backup_root)


__all__ = ["MachineQaFixtureCredentialOperations"]
