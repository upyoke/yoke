"""Remote execution, path safety, and cleanup for Machine QA fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import shlex
from typing import Callable, Protocol

from yoke_cli.config.path_doctor import (
    PathStateContract,
    resolve_path_state_contract,
)

from yoke_core.domain.host_control_executor import HostActionResult
from yoke_core.domain.machine_qa_fixture_constants import (
    CAMPAIGN_WORKSPACE_PATHS,
    EMPTY_TOKEN_PATH,
    FAKE_TOKEN_PATH,
    INVALID_TOKEN_PATH,
    LONG_PROJECT_PATH,
    MISSING_TOKEN_PATH,
    SOURCE_DEV_GIT_CONFIG_PATH,
    STATE_PROJECT_MISSING_PATH,
    STATE_PROJECT_ONE_PATH,
    STATE_PROJECT_TWO_PATH,
)
from yoke_core.domain.machine_qa_fixture_paths import FIXTURE_ROOT
from yoke_core.domain.machine_qa_fixture_validation import (
    MachineQaFixtureOperationError,
)


class RemoteCommandResult(Protocol):
    """Minimum result shape required from an injected remote runner."""

    returncode: int


class RemoteRunner(Protocol):
    """Run one executor-authored shell command on the controlled host."""

    def __call__(
        self,
        command: str,
        *,
        timeout: int = 60,
    ) -> RemoteCommandResult: ...


class RemoteTextUploader(Protocol):
    """Write executor-authored text to one controlled-host path."""

    def __call__(self, path: str, content: str) -> None: ...


@dataclass(frozen=True)
class ServiceCleanup:
    """Identity needed to stop one executor-owned remote service."""

    identity_path: str
    identity: str


@dataclass
class TokenRestore:
    """Backup metadata for one temporary token replacement."""

    target_path: str
    backup_path: str
    existed: bool
    restore_required: bool = False


@dataclass
class AuthStateRestore:
    """Opaque backup metadata for product config and credential state."""

    config_path: str
    secrets_path: str
    backup_root: str
    config_existed: bool
    secrets_existed: bool
    restore_required: bool = False


class RemoteFixtureFailure(RuntimeError):
    """A remote fixture command or upload failed."""


def shell_command(*argv: object) -> str:
    """Build one safely quoted executor-authored remote command."""
    return shlex.join([str(value) for value in argv])


def path_is_within(path: str, root: str) -> bool:
    """Return whether a normalized absolute path is at or below a root."""
    selected = PurePosixPath(path)
    parent = PurePosixPath(root)
    return selected == parent or parent in selected.parents


class MachineQaFixtureRuntime:
    """Own injected host adapters, bounded paths, and retryable cleanup."""

    def __init__(
        self,
        *,
        run_remote: RemoteRunner,
        upload_text: RemoteTextUploader,
        home: str,
        path_state: PathStateContract | None = None,
        prepare_terminal_size: Callable[[int, int], None] | None = None,
    ) -> None:
        selected_home = PurePosixPath(home)
        if (
            not selected_home.is_absolute()
            or str(selected_home) == "/"
            or ".." in selected_home.parts
        ):
            raise MachineQaFixtureOperationError(
                "fixture executor requires a bounded absolute host home"
            )
        self._run_remote = run_remote
        self._upload_remote = upload_text
        self._prepare_terminal_size = prepare_terminal_size
        self.home = str(selected_home)
        self.path_state = path_state or resolve_path_state_contract(
            env={"HOME": self.home, "SHELL": "/bin/zsh"}
        )
        if self.path_state.home != self.home:
            raise MachineQaFixtureOperationError(
                "fixture PATH contract does not match the bounded host home"
            )
        if self.path_state.yoke_bin == self.home or not path_is_within(
            self.path_state.yoke_bin, self.home
        ):
            raise MachineQaFixtureOperationError(
                "fixture launcher escapes the bounded host home"
            )
        self._services: dict[int, ServiceCleanup] = {}
        self._restores: list[TokenRestore | AuthStateRestore] = []
        self._accepting = True
        self._closed = False

    def close(self) -> HostActionResult:
        """Retry teardown for services and temporary secret restoration."""
        self._accepting = False
        if self._closed:
            return HostActionResult(True, {"operations": []})
        rows: list[dict[str, str]] = []
        failed = False
        for port, cleanup in reversed(tuple(self._services.items())):
            try:
                self._stop_service(cleanup)
            except RemoteFixtureFailure:
                rows.append(
                    {
                        "id": "fixture.yoke-api-start",
                        "outcome": "failed",
                    }
                )
                failed = True
            else:
                rows.append(
                    {
                        "id": "fixture.yoke-api-start",
                        "outcome": "passed",
                    }
                )
                self._services.pop(port, None)
        for restore in reversed(tuple(self._restores)):
            operation_id = (
                "machine.token-file-prepare"
                if isinstance(restore, TokenRestore)
                else "machine.yoke-auth-clear"
            )
            try:
                if isinstance(restore, TokenRestore):
                    self._restore_token(restore)
                else:
                    self._restore_auth_state(restore)
            except RemoteFixtureFailure:
                rows.append(
                    {
                        "id": operation_id,
                        "outcome": "failed",
                    }
                )
                failed = True
            else:
                rows.append(
                    {
                        "id": operation_id,
                        "outcome": "passed",
                    }
                )
                self._restores.remove(restore)
        self._closed = not self._services and not self._restores
        return HostActionResult(
            ok=not failed,
            evidence={"operations": rows},
            error_code="fixture_cleanup_failed" if failed else None,
        )

    def __enter__(self) -> "MachineQaFixtureRuntime":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def _invoke(self, command: str, *, timeout: int = 60) -> int:
        try:
            result = self._run_remote(command, timeout=timeout)
            returncode = int(result.returncode)
        except Exception as exc:
            raise RemoteFixtureFailure from exc
        return returncode

    def _run(self, command: str, *, timeout: int = 60) -> None:
        if self._invoke(command, timeout=timeout) != 0:
            raise RemoteFixtureFailure

    def _upload(
        self,
        path: str,
        content: str,
        *,
        mode: int | None = None,
    ) -> None:
        self._assert_upload_path(path)
        try:
            self._upload_remote(path, content)
        except Exception as exc:
            raise RemoteFixtureFailure from exc
        if mode is not None:
            self._run(shell_command("/bin/chmod", f"{mode:o}", path))

    def _resolve_path(self, value: str) -> str:
        if value.startswith("~/"):
            selected = PurePosixPath(self.home) / value[2:]
        else:
            selected = PurePosixPath(value)
        if not selected.is_absolute() or ".." in selected.parts:
            raise MachineQaFixtureOperationError(
                "fixture path is not a bounded absolute target"
            )
        return str(selected)

    def _assert_upload_path(self, path: str) -> None:
        selected = self._resolve_path(path)
        tmp_roots = (
            *CAMPAIGN_WORKSPACE_PATHS,
            FIXTURE_ROOT,
            STATE_PROJECT_ONE_PATH,
            STATE_PROJECT_TWO_PATH,
            STATE_PROJECT_MISSING_PATH,
            LONG_PROJECT_PATH,
        )
        yoke_home = f"{self.home}/.yoke"
        allowed = (
            any(path_is_within(selected, root) for root in tmp_roots)
            or selected
            in {
                FAKE_TOKEN_PATH,
                EMPTY_TOKEN_PATH,
                INVALID_TOKEN_PATH,
            }
            or selected == f"{yoke_home}/config.json"
            or path_is_within(selected, f"{yoke_home}/secrets")
            or path_is_within(
                selected,
                f"{yoke_home}/onboarding-runs/apply-reports",
            )
        )
        if not allowed:
            raise RuntimeError("executor selected an unowned upload path")

    def _delete(self, *paths: str) -> None:
        resolved = [self._resolve_path(path) for path in paths]
        for path in resolved:
            self._assert_delete_path(path)
        self._run(shell_command("/bin/rm", "-rf", "--", *resolved))

    def _assert_delete_path(self, path: str) -> None:
        exact = {
            *CAMPAIGN_WORKSPACE_PATHS,
            FIXTURE_ROOT,
            STATE_PROJECT_ONE_PATH,
            STATE_PROJECT_TWO_PATH,
            STATE_PROJECT_MISSING_PATH,
            MISSING_TOKEN_PATH,
            EMPTY_TOKEN_PATH,
            INVALID_TOKEN_PATH,
            FAKE_TOKEN_PATH,
            SOURCE_DEV_GIT_CONFIG_PATH,
            self.path_state.yoke_bin,
            f"{self.home}/.local/share/uv/tools/yoke-cli",
            f"{self.home}/.yoke/config.json",
            f"{self.home}/.yoke/secrets",
            f"{self.home}/.yoke/secrets/stage.token",
            LONG_PROJECT_PATH,
        }
        within_campaign = any(
            path_is_within(path, root) for root in CAMPAIGN_WORKSPACE_PATHS
        )
        if (
            path not in exact
            and not within_campaign
            and not path_is_within(path, FIXTURE_ROOT)
        ):
            raise RuntimeError("executor selected an unowned destructive path")

    def _yoke_bin(self) -> str:
        return self.path_state.yoke_bin

    def _installed_yoke_python(self, *argv: object) -> str:
        """Run an uploaded program with the installed launcher's interpreter."""
        script = (
            'launcher="$1"; shift; '
            'IFS= read -r shebang < "$launcher" || exit 64; '
            'interpreter="${shebang#\\#!}"; '
            '[[ "$interpreter" == /* && -x "$interpreter" ]] || exit 65; '
            'exec "$interpreter" "$@"'
        )
        return shell_command(
            "/bin/zsh",
            "-fc",
            script,
            "yoke-machine-qa",
            self._yoke_bin(),
            *argv,
        )


__all__ = [
    "AuthStateRestore",
    "MachineQaFixtureRuntime",
    "RemoteCommandResult",
    "RemoteFixtureFailure",
    "RemoteRunner",
    "RemoteTextUploader",
    "ServiceCleanup",
    "TokenRestore",
    "path_is_within",
    "shell_command",
]
