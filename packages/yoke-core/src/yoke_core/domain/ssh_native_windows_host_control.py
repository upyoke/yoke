"""Machine QA protocol binding for the native Windows adapter."""

from pathlib import PureWindowsPath

from yoke_contracts.runtime_ports.ssh_windows_host_operations import (
    get_ssh_windows_host_operations,
)
from yoke_contracts.test_machine_types import HostActionResult

SshNativeWindowsHostOperations = (
    get_ssh_windows_host_operations().SshNativeWindowsHostOperations
)


class SshNativeWindowsHostControl(SshNativeWindowsHostOperations):
    def __init__(self, material, *, elevated=False, login_user=None):
        self.material = material
        self._pending_terminal_size = (120, 40)
        super().__init__(
            settings=material.settings,
            key_path=material.secret_paths["ssh_private_key"],
            secret_values=tuple(material.secrets.values()),
            elevated=elevated,
            login_user=login_user,
        )

    def variant(self, *, elevated=False, second_user=False):
        """The same lab as the elevated test user or as the second local user."""
        return type(self)(
            self.material,
            elevated=elevated,
            login_user=self.SECOND_USER if second_user else None,
        )

    def run_system_script(self, script, *, timeout):
        from yoke_core.domain.native_windows_machine_fixtures import run_system_script

        return run_system_script(self.material, script, timeout=timeout)

    def project_public_key(self):
        from yoke_core.domain.native_windows_machine_fixtures import project_public_key

        return project_public_key(self.material)

    def read_text(self, path):
        return self.read_remote_text(path)

    def write_text(self, path, content):
        self.upload_remote_text(path, content)

    def copy_file_to(self, path, destination, *, max_bytes, refused_root):
        selected, refused = PureWindowsPath(path), PureWindowsPath(refused_root)
        if (
            not selected.is_absolute()
            or ".." in selected.parts
            or selected == refused
            or refused in selected.parents
        ):
            raise ValueError(
                "windows_host_copy_refused: choose a literal regular file outside the refused root"
            )
        content = self.read_remote_bytes(path, max_bytes)
        destination.write_bytes(content)
        return len(content)

    def capture_terminal_checkpoint(self, *, focused_window=False):
        from yoke_core.domain.machine_terminal_screenshot import (
            capture_terminal_checkpoint,
        )

        return capture_terminal_checkpoint(self)

    def create_fixture_operation_runner(self):
        from yoke_core.domain.native_windows_fixture import NativeWindowsFixture

        return NativeWindowsFixture(self)

    def _set_terminal_size(self, columns, rows):
        if not 1 <= columns <= 500 or not 1 <= rows <= 500:
            raise ValueError("terminal size is outside registered bounds")
        self._pending_terminal_size = (columns, rows)

    def _entry_surface(self, value):
        # PowerShell escapes one literal string by doubling single quotes.
        resolved = value.replace(
            "{yoke_bin}", "'" + self.path_state.yoke_bin.replace("'", "''") + "'"
        )
        return resolved

    def run_command(self, argv, *, required_session_context=None, timeout=60):
        """Show Yoke's browser pages on the test user's desktop.

        An SSH command runs in session zero, where no window is visible and
        OpenSSH ends its children with the session. ``yoke browser open`` and
        the managed ``yoke qa browser`` commands therefore start in the
        interactive desktop through the scheduled-task handoff, with the
        installed Yoke's Python.
        """
        operations = get_ssh_windows_host_operations()
        if not operations.opens_identity_page(argv):
            return super().run_command(
                argv, required_session_context=required_session_context, timeout=timeout
            )
        script = operations.yoke_python_command([self.path_state.yoke_bin, *argv[1:]])
        result = operations.desktop_script(self, script, timeout=timeout)
        result.desktop_session = "interactive"
        return result

    def run_terminal_case(self, **kwargs):
        from yoke_contracts.runtime_ports.ssh_windows_host_operations import (
            get_ssh_windows_host_operations,
        )

        kwargs["entry_surface"] = self._entry_surface(kwargs["entry_surface"])
        kwargs.setdefault("size", self._pending_terminal_size)
        result = get_ssh_windows_host_operations().run_native_terminal_case(
            self, **kwargs
        )
        return HostActionResult(
            result.ok,
            {**result.evidence, "connection": self.check_connection().evidence},
            result.error_code,
        )

    def run_terminal_recipe(
        self,
        *,
        entry_surface,
        required_completion,
        config,
        progress_callback=None,
        allowed_operator_urls=(),
    ):
        from yoke_core.domain.native_windows_terminal_recipe import execute_recipe

        return execute_recipe(
            self,
            entry_surface=self._entry_surface(entry_surface),
            required_completion=required_completion,
            config=config,
            progress_callback=progress_callback,
            allowed_operator_urls=allowed_operator_urls,
        )
