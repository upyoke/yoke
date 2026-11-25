"""Native Windows 11 QA over OpenSSH, PowerShell and an interactive desktop."""

import json

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.baseline import profile_operation, reach_baseline
from yoke_harness.native_windows.console import probe_console, verify_console
from yoke_harness.native_windows.desktop import capture_desktop
from yoke_harness.native_windows.machine_fixtures import SECOND_USER, apply_fixture
from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_harness.native_windows.mission import WindowsMissionOperations
from yoke_harness.test_machine_reset_identity import retire_reset_identity
from yoke_harness.native_windows.transport import (
    HOST_RESOURCES_EXHAUSTED,
    HOST_RESOURCES_RECOVERY,
    WindowsTransport,
)


MINIMUM_FREE_COMMIT_BYTES = 1024**3
# GetPerformanceInfo works under the standard SSH user. WMI performance
# counters on the labs require permissions that account does not have.
COMMIT_MEMORY_PROBE = r"""
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class CommitMemory {
    [StructLayout(LayoutKind.Sequential)]
    public struct Info {
        public uint Size;
        public UIntPtr Total, Limit, Peak, Physical, Available, Cache,
            Kernel, Paged, Nonpaged, PageSize;
        public uint Handles, Processes, Threads;
    }
    [DllImport("psapi.dll")]
    public static extern bool GetPerformanceInfo(out Info info, uint size);
}
'@
$info=New-Object 'CommitMemory+Info'
if(![CommitMemory]::GetPerformanceInfo([ref]$info,[Runtime.InteropServices.Marshal]::SizeOf($info))){
    throw 'GetPerformanceInfo failed'
}
$page=$info.PageSize.ToUInt64()
@{commit_limit_bytes=$info.Limit.ToUInt64()*$page;committed_bytes=$info.Total.ToUInt64()*$page} | ConvertTo-Json -Compress
"""


class SshNativeWindowsHostOperations(WindowsMissionOperations, WindowsTransport):
    """A standard Windows user; no WSL commands or Linux desktop intermediates."""

    SECOND_USER = SECOND_USER

    def machine_fixture(self, name, *, undo):
        """Apply or undo one machine-wide fixture as SYSTEM; see machine_fixtures."""
        return apply_fixture(self, name, undo=undo)

    def check_connection(self):
        commit = self._run(COMMIT_MEMORY_PROBE, timeout=20)
        try:
            counters = json.loads(commit.stdout)
        except ValueError:
            counters = None
        if not isinstance(counters, dict):
            counters = {}
        limit = counters.get("commit_limit_bytes")
        used = counters.get("committed_bytes")
        if (
            commit.returncode
            or type(limit) is not int or limit <= 0
            or type(used) is not int or used < 0
        ):
            return HostActionResult(
                False,
                {
                    "reason": "Windows commit memory could not be measured.",
                    "recovery": "Check PowerShell and GetPerformanceInfo on the host, then rerun test-machine verify.",
                    "exit_code": commit.returncode,
                    "stdout": bounded_machine_qa_diagnostic(commit.stdout, self.secret_values),
                    "stderr": bounded_machine_qa_diagnostic(commit.stderr, self.secret_values),
                },
                "native_windows_commit_memory_unverified",
            )
        headroom = max(0, limit - used)
        memory_evidence = {
            "commit_limit_bytes": limit,
            "committed_bytes": used,
            "free_commit_bytes": headroom,
            "minimum_free_commit_bytes": MINIMUM_FREE_COMMIT_BYTES,
        }
        if headroom < MINIMUM_FREE_COMMIT_BYTES:
            return HostActionResult(
                False,
                {
                    **memory_evidence,
                    "reason": (
                        "Windows has less than "
                        f"{MINIMUM_FREE_COMMIT_BYTES // 1024**3} GiB of free commit memory."
                    ),
                    "recovery": HOST_RESOURCES_RECOVERY,
                },
                HOST_RESOURCES_EXHAUSTED,
            )
        facts = self._run(
            r"""$release=if(Get-Command yoke.cmd -ErrorAction SilentlyContinue){(& yoke.cmd --version) -join ' '}else{'absent'}
@{yoke_release=$release} | ConvertTo-Json -Compress
""",
            timeout=30,
        )
        try:
            observed = json.loads(facts.stdout)
        except ValueError:
            observed = {}
        # An uninstalled Yoke is a valid fresh-host state.
        ok = facts.returncode == 0
        from yoke_harness.golden_harness_clis import probe_harness_cli_versions

        versions = probe_harness_cli_versions(self) if ok else {}
        return HostActionResult(
            ok,
            {
                **memory_evidence,
                "transport": "ssh",
                "os": "windows",
                "edition": self.windows_facts["edition"],
                "build": self.windows_facts["build"],
                "harness_version": versions,
                "yoke_release": observed.get("yoke_release") or "absent",
                "runner_materialized": ok,
                **(
                    {}
                    if ok
                    else {
                        "reason": "The native startup probe failed.",
                        "recovery": "Check PowerShell and yoke.cmd on the host, then rerun test-machine verify.",
                    }
                ),
            },
            None if ok else "native_windows_startup_probe_failed",
        )

    def capture_screenshot(self, *, focused_window=False):
        return capture_desktop(self, focused_window=focused_window)

    def drive_desktop(self, request, *, secrets=()):
        from yoke_harness.native_windows.desktop_input import drive_desktop

        return drive_desktop(self, request, secrets=secrets)

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
        retirement = retire_reset_identity(self, native_windows=True)
        if not retirement.ok:
            return retirement
        restored = profile_operation(self, "reset", self.golden_baseline_path)
        if not restored.ok:
            return HostActionResult(
                False, {**retirement.evidence, **restored.evidence}, restored.error_code
            )
        console = probe_console(self, set_resolution=True)
        if not console.ok:
            return HostActionResult(
                False, {**retirement.evidence, **console.evidence}, console.error_code
            )
        absent = self._run(
            "$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User'); if(Get-Command yoke,yoke.cmd,uv,uvx -ErrorAction SilentlyContinue){exit 1}"
        )
        return HostActionResult(
            absent.returncode == 0,
            {
                **retirement.evidence,
                **restored.evidence,
                "windows_console": console.evidence,
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
        from yoke_harness.standard_baseline_probes import prove_current_standard

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
        return prove_current_standard(
            "windows", document, lambda current: prove_document(self, current)
        )

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
        return verify_console(self, self.diagnose_terminal_bridge)
