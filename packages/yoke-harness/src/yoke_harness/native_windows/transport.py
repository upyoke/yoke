"""PowerShell framing and literal paths for Windows OpenSSH."""

import base64
import json
import subprocess
import time
from pathlib import PureWindowsPath
from types import SimpleNamespace

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows.powershell import encoded, quote
from yoke_harness.native_windows.standard_staging import verified_payload
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


HOST_RESOURCES_EXHAUSTED = "native_windows_host_resources_exhausted"
HOST_RESOURCES_RECOVERY = "Free memory or enlarge the Windows page file, then retry."
HOST_FACTS_RETRY_DELAY_SECONDS = 1


def command(argv) -> str:
    if not argv or not str(argv[0]):
        raise ValueError("host_control command requires a non-empty executable")
    return "& " + " ".join(quote(value) for value in argv)


def process_script(argv):
    if not argv or not str(argv[0]):
        raise ValueError("host_control command requires a non-empty executable")
    if str(argv[0]).lower().endswith((".cmd", ".bat")):
        return command(argv) + "; exit $LASTEXITCODE"
    # Windows PowerShell 5 drops empty arguments when invoking a native program
    # with its call operator. ProcessStartInfo uses the Windows argv contract.
    return f"""
$info=[Diagnostics.ProcessStartInfo]::new()
$info.FileName={quote(argv[0])}
$info.Arguments={quote(subprocess.list2cmdline(list(argv[1:])))}
$info.UseShellExecute=$false
$info.RedirectStandardOutput=$true
$info.RedirectStandardError=$true
$p=[Diagnostics.Process]::new(); $p.StartInfo=$info
if(!$p.Start()){{throw 'windows_process_start_failed: repair the native executable and retry'}}
$out=$p.StandardOutput.ReadToEndAsync(); $err=$p.StandardError.ReadToEndAsync()
$p.WaitForExit()
[Console]::Out.Write($out.Result); [Console]::Error.Write($err.Result)
$code=$p.ExitCode; $p.Dispose(); exit $code
"""


class WindowsTransport(SshTestMachineTransport):
    """Use encoded scripts so neither cmd.exe nor ssh reparses user arguments."""

    elevated = False
    login_user = None
    admin_refusal = None
    task_logon_type = 3

    def __init__(self, *, elevated=False, login_user=None, **kwargs):
        # An elevated control requires an administrator token; the second
        # user logs in by name through `-l`, never as a `user@host` string.
        self.elevated = elevated
        self.login_user = login_user
        self.admin_refusal = None
        # S4U (2) for a user with no console session; else the console token (3).
        self.task_logon_type = 2 if login_user else 3
        # The parent resolves POSIX shell state on the controller. Windows paths
        # must instead be resolved from the remote host's Windows facts.
        super().__init__(**kwargs)
        root = PureWindowsPath(self.home)
        tools = str(root / ".local" / "bin")
        self.path_state = SimpleNamespace(
            home=self.home,
            tool_bin_dir=tools,
            yoke_bin=str(PureWindowsPath(tools) / "yoke.cmd"),
            startup_file=str(
                root / "Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1"
            ),
            supported_startup_files=(),
        )

    @property
    def test_user(self):
        return self._user

    def refresh_host_facts(self):
        """Re-read the token after a SYSTEM change; an admin token still refuses."""
        self.admin_refusal = None
        facts = self._host_facts()
        if self.admin_refusal is not None:
            raise self.admin_refusal
        return facts

    def _ssh_argv(self, script):
        # An admin token without --elevated fails every command loudly, but
        # only once one runs: a reset must first reach its fixture undo.
        if self.admin_refusal is not None:
            raise self.admin_refusal
        wrapped = (
            "$ErrorActionPreference='Stop'; "
            # Progress records reach a redirected stderr as CLIXML and bury
            # the refusal text callers return as recovery.
            "$ProgressPreference='SilentlyContinue'; "
            "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
            "try { " + script + " } catch { [Console]::Error.WriteLine($_); exit 1 }"
        )
        if len(encoded(wrapped)) + 80 >= 8000:
            raise RuntimeError("windows_command_too_long: use verified script staging")
        argv = super()._ssh_argv(
            "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
            + encoded(wrapped)
        )
        if self.login_user:
            at = argv.index(f"{self._user}@{self._host}")
            argv[at : at + 1] = ["-l", self.login_user, self._host]
        return argv

    def _run(self, command, *, input_text=None, timeout=60, debug_log=None):
        # Windows OpenSSH commonly launches through cmd.exe's 8191-character
        # boundary. Stream larger scripts into a private per-user file first.
        if len(encoded(command)) < 6000:
            return super()._run(
                command, input_text=input_text, timeout=timeout, debug_log=debug_log
            )
        with verified_payload(self, command.encode("utf-8-sig")) as stage:
            stage.execution_pending = True
            result = super()._run(
                f"& {stage.path}", input_text=input_text, timeout=timeout, debug_log=debug_log,
            )
            # A lost SSH session or local timeout does not prove guest exit.
            stage.primary_result = result
            stage.execution_pending = result.returncode in (124, 255)
            result.staging_diagnostics = stage.diagnostics
            return result

    def _host_facts(self):
        try:
            return self._probe_host_facts()
        except HostControlLocalError as error:
            if error.code != HOST_RESOURCES_EXHAUSTED:
                raise
        time.sleep(HOST_FACTS_RETRY_DELAY_SECONDS)
        return self._probe_host_facts()

    def _probe_host_facts(self):
        result = self._run(
            r"""$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$admin=([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$version=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
@{home=$env:USERPROFILE;shell='powershell.exe';os='Windows';admin=$admin;
  edition=$version.EditionID;build=$version.CurrentBuildNumber;user=$identity.Name} | ConvertTo-Json -Compress
""",
            timeout=20,
        )
        code = "native_windows_host_facts_failed"
        detail = "Native Windows host-facts command failed."
        recovery = "Repair the named SSH or PowerShell failure, then retry host facts."
        output = f"{result.stdout}\n{result.stderr}".casefold()
        startup_failed = (
            "paging file is too small" in output
            or (
                "system.management.automation" in output
                and ("could not load" in output or "failed to load" in output)
            )
        )
        facts = None
        if not result.returncode and not startup_failed:
            try:
                facts = json.loads(result.stdout)
            except ValueError:
                pass
        if startup_failed or (not result.returncode and not isinstance(facts, dict)):
            code = HOST_RESOURCES_EXHAUSTED
            detail = "PowerShell could not start or returned no Windows host-facts object."
            recovery = HOST_RESOURCES_RECOVERY
        elif isinstance(facts, dict):
            code = "native_windows_host_facts_invalid"
            detail = "Native Windows host facts have an invalid schema."
            recovery = "Repair the host-facts probe output and retry; it must describe Windows, an absolute home and a boolean admin field."
            if (
                facts.get("os") == "Windows"
                and type(facts.get("admin")) is bool
                and isinstance(facts.get("home"), str)
                and PureWindowsPath(facts["home"]).is_absolute()
                and facts.get("shell") == "powershell.exe"
                and all(isinstance(facts.get(key), str) and facts[key]
                        for key in ("edition", "build", "user"))
                and facts["build"].isascii() and facts["build"].isdigit()
            ):
                if self.os == "wsl" or facts["admin"] is bool(self.elevated):
                    self.windows_facts = facts
                    return facts
                if not self.elevated:
                    self.windows_facts = facts
                    self.admin_refusal = HostControlLocalError(
                        code="native_windows_test_user_required",
                        phase="host_facts_ssh",
                        detail="Native Windows QA requires a standard Windows SSH user; this token is an administrator.",
                        recovery_hint=(
                            "Undo the grant with `yoke qa mission host-command --fixture grant-admin --undo`, "
                            "or run `yoke test-machine reset`, which undoes every machine fixture; "
                            "pass --elevated only for a command that needs the grant."
                        ),
                    )
                    return facts
                code = "native_windows_elevation_not_granted"
                detail = "--elevated needs an administrator token; this SSH token is standard."
                recovery = "Apply `yoke qa mission host-command --fixture grant-admin` first, then rerun with --elevated."
        raise HostControlLocalError(
            code=code,
            phase="host_facts_ssh",
            detail=detail,
            recovery_hint=recovery,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            secrets=self.secret_values,
        )

    def probe_path(self, surface):
        if surface not in {"login", "ssh"}:
            raise ValueError("unknown Windows PATH surface")
        script = "$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User'); "
        if surface == "login":
            script += "if(Test-Path $PROFILE){. $PROFILE}; "
        script += "$env:Path"
        result = self._run(script, timeout=20)
        if result.returncode:
            raise RuntimeError(
                "windows_path_probe_failed: repair the user's PowerShell profile and retry"
            )
        return tuple(part for part in result.stdout.strip().split(";") if part)

    def run_command(self, argv, *, required_session_context=None, timeout=60):
        script = process_script(argv)
        if required_session_context == "gui":
            from yoke_harness.native_windows.desktop import desktop_script

            from yoke_harness.native_windows.display_geometry import ENSURE

            # An S4U task has no display to size.
            ensure = "" if self.login_user else ENSURE
            result = desktop_script(self, "$ErrorActionPreference='Stop'\n" + ensure + script, timeout=timeout)
            if self.login_user:
                result.desktop_session = "s4u_task"
            return result
        if required_session_context is not None:
            raise ValueError("unknown Windows session context")
        return self._run(script, timeout=timeout)

    def upload_remote_text(self, path, content):
        self._upload_bytes(
            path,
            content.encode("utf-8-sig" if path.lower().endswith(".ps1") else "utf-8"),
        )

    def _upload_bytes(self, path, content):
        # Small and large uploads share SFTP and independent byte/ACL checks.
        with verified_payload(self, content) as stage:
            stage.execution_pending = True
            result = super()._run(
                f"New-Item -ItemType Directory -Force (Split-Path {quote(path)}) | Out-Null; Move-Item -LiteralPath {stage.path} -Destination {quote(path)} -Force",
            )
            stage.primary_result = result
            stage.execution_pending = result.returncode in (124, 255)
            if result.returncode:
                error = HostControlLocalError(
                    code="windows_host_file_write_failed", phase="file_commit",
                    detail="Verified Windows upload could not be committed.",
                    recovery_hint="Inspect destination and staging diagnostics before retrying an ambiguous commit.",
                    exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                    secrets=getattr(self, "secret_values", ()),
                )
                raise error
        return True

    def read_remote_text(self, path):
        result = self._run(
            f"if(Test-Path -LiteralPath {quote(path)}){{[IO.File]::ReadAllText({quote(path)})}}"
        )
        if result.returncode:
            raise HostControlLocalError(
                code="windows_host_file_read_failed", phase="file_read",
                detail=f"Windows host file read failed: {path}",
                recovery_hint="Inspect the read diagnostics; retry if the file was being written, otherwise repair access to the named file.",
                exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                secrets=getattr(self, "secret_values", ()),
            )
        return result.stdout or None

    def read_remote_bytes(self, path, max_bytes):
        selected = PureWindowsPath(path)
        if not selected.is_absolute() or ".." in selected.parts:
            raise ValueError(
                "windows_host_file_unsafe: choose an absolute regular file without parent traversal"
            )
        result = self._run(f"""
$p={quote(path)}
$entry=Get-Item -LiteralPath $p
$current=$entry
while($null -ne $current){{
 if($current.Attributes -band [IO.FileAttributes]::ReparsePoint){{throw 'windows_host_file_unsafe: remove links from the file path'}}
 $current=if($current.PSIsContainer){{$current.Parent}}else{{$current.Directory}}
}}
if($entry.PSIsContainer -or $entry.Length -gt {int(max_bytes)}){{throw 'windows_host_file_size_refused: choose a bounded regular file'}}
[Convert]::ToBase64String([IO.File]::ReadAllBytes($p))
""")
        if result.returncode:
            raise ValueError(
                "windows_host_file_read_failed: repair the bounded regular file and retry; "
                + result.stderr[-500:]
            )
        content = base64.b64decode(result.stdout.strip(), validate=True)
        if len(content) > max_bytes:
            raise ValueError(
                "windows_host_file_size_refused: reduce the file size and retry"
            )
        return content
