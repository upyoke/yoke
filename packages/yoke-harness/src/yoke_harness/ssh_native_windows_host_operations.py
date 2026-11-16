"""Native Windows 11 QA over OpenSSH, PowerShell and an interactive desktop."""

from contextlib import contextmanager
import json

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.baseline import profile_operation, reach_baseline
from yoke_harness.native_windows.desktop import capture_desktop
from yoke_harness.native_windows.journal import journal_operation
from yoke_harness.native_windows.transport import WindowsTransport


class SshNativeWindowsHostOperations(WindowsTransport):
    """A standard Windows user; no WSL commands or Linux desktop intermediates."""

    def bind_qa_lease(self, lease_id):
        self.qa_lease_id = lease_id
        journal_operation(self, "restore")

    def journal_settings(self, action):
        return journal_operation(self, action)

    @contextmanager
    def machine_settings_guard(self):
        # Recovery belongs to the next serial lease before any new mutation.
        journal_operation(self, "restore")
        journal_operation(self, "capture")
        try:
            yield
        finally:
            journal_operation(self, "restore")

    def check_connection(self):
        facts = self._run(
            r"""$features=@(Get-CimInstance Win32_OptionalFeature | Where-Object {
 $_.Name -in @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform') -and $_.InstallState -eq 1
})
$release=if(Get-Command yoke.cmd -ErrorAction SilentlyContinue){(& yoke.cmd --version) -join ' '}else{'absent'}
@{wsl_absent=($features.Count -eq 0);yoke_release=$release} | ConvertTo-Json -Compress
""",
            timeout=30,
        )
        try:
            observed = json.loads(facts.stdout)
        except ValueError:
            observed = {}
        # An uninstalled Yoke is a valid fresh-host state.
        ok = facts.returncode == 0 and observed.get("wsl_absent") is True
        from yoke_harness.golden_harness_clis import probe_harness_cli_versions

        versions = probe_harness_cli_versions(self) if ok else {}
        return HostActionResult(
            ok,
            {
                "transport": "ssh",
                "os": "windows",
                "edition": self.windows_facts["edition"],
                "build": self.windows_facts["build"],
                "harness_version": versions,
                "yoke_release": observed.get("yoke_release") or "absent",
                "wsl_absent": observed.get("wsl_absent"),
                "runner_materialized": ok,
                "observed_outcome": "passed" if ok else "refused",
                **(
                    {}
                    if ok
                    else {
                        "reason": "WSL is present or the native startup probe failed",
                        "recovery": "Remove WSL and VirtualMachinePlatform from this dedicated Windows 11 host, reboot, and verify native SSH again.",
                    }
                ),
            },
            None if ok else "native_windows_startup_probe_failed",
        )

    def capture_screenshot(self, *, focused_window=False):
        return capture_desktop(self, focused_window=focused_window)

    def capture_golden_baseline(self, destination, *, probes_document=None):
        from yoke_harness.golden_harness_clis import record_golden_harness_clis
        from yoke_harness.native_windows.probes import capture_document, prove_document

        try:
            document = capture_document(self, probes_document)
            proved = prove_document(self, document)
        except ValueError as exc:
            return HostActionResult(
                False, {"recovery": str(exc)}, "baseline_probes_invalid"
            )
        if not proved.ok:
            return proved
        result = profile_operation(self, "capture", destination)
        if not result.ok:
            return result
        versions = record_golden_harness_clis(self, destination)
        if versions.ok:
            self.upload_remote_text(destination + ".probes", document)
            self.upload_remote_text(
                destination + "\\sealed", "native-windows-profile-v1"
            )
        return HostActionResult(
            versions.ok,
            {
                **result.evidence,
                **versions.evidence,
                "probes": proved.evidence["probes"],
            },
            versions.error_code,
        )

    def reset_installer_test_host(self):
        if not self.golden_baseline_path:
            return HostActionResult(
                False,
                {
                    "recovery": "Capture a native golden outside the test profile and register its Windows path."
                },
                "golden_baseline_not_declared",
            )
        restored = profile_operation(self, "reset", self.golden_baseline_path)
        if not restored.ok:
            return restored
        absent = self._run(
            "$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User'); if(Get-Command yoke,yoke.cmd,uv,uvx -ErrorAction SilentlyContinue){exit 1}"
        )
        return HostActionResult(
            absent.returncode == 0,
            {
                **restored.evidence,
                "path_state": {"yoke_tools_resolve": absent.returncode != 0},
                **(
                    {}
                    if not absent.returncode
                    else {
                        "recovery": "Remove Yoke and uv from the golden and machine PATH, capture a new golden, then reset again."
                    }
                ),
            },
            None if absent.returncode == 0 else "reset_absence_not_proved",
        )

    def prove_user_equivalent(self):
        from yoke_harness.native_windows.probes import prove_document

        document = (
            self.read_remote_text(self.golden_baseline_path + ".probes")
            if self.golden_baseline_path
            else None
        )
        if not document:
            return HostActionResult(
                False,
                {
                    "recovery": "Capture a new native golden with canonical harness probes."
                },
                "baseline_probes_not_declared",
            )
        return prove_document(self, document)

    def reach_baseline(self, name):
        return reach_baseline(self, name)

    def run_machine_assertions(self, assertions):
        rows = []
        connection = self.check_connection()
        if not connection.ok:
            return HostActionResult(
                False, {"connection": connection.evidence}, connection.error_code
            )
        for assertion in assertions:
            result = self.run_command(
                assertion["argv"],
                required_session_context=assertion.get("required_session_context"),
            )
            expected = int(assertion.get("expected_exit", 0))
            rows.append(
                {
                    "argv": assertion["argv"],
                    "expected_exit": expected,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            if result.returncode != expected:
                return HostActionResult(
                    False,
                    {"assertions": rows, "connection": connection.evidence},
                    "machine_assertion_failed",
                )
        return HostActionResult(
            True, {"assertions": rows, "connection": connection.evidence}
        )

    def diagnose_terminal_bridge(self):
        from yoke_harness.native_windows.terminal import run_native_terminal_case

        token = "YOKE_BRIDGE_NATIVE"
        return run_native_terminal_case(
            self,
            entry_surface="Write-Host ('YOKE_BRIDGE_'+'NATIVE')",
            required_completion="bridge",
            steps=[{"key": "bridge", "expect": token}],
            capture_checkpoints=["bridge"],
        )

    def check_terminal_bridge(self):
        return self.diagnose_terminal_bridge()
