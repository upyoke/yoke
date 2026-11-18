"""PowerShell framing and literal paths for Windows OpenSSH."""

import base64
import json
import subprocess
from pathlib import PureWindowsPath
from types import SimpleNamespace

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows.powershell import encoded, quote
from yoke_harness.native_windows.standard_staging import verified_payload
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


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

    def __init__(self, **kwargs):
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

    def _ssh_argv(self, script):
        wrapped = (
            "$ErrorActionPreference='Stop'; "
            "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
            "try { " + script + " } catch { [Console]::Error.WriteLine($_); exit 1 }"
        )
        if len(encoded(wrapped)) + 80 >= 8000:
            raise RuntimeError("windows_command_too_long: use verified script staging")
        return super()._ssh_argv(
            "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
            + encoded(wrapped)
        )

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
            stage.execution_pending = result.returncode in (124, 255)
            result.staging_diagnostics = stage.diagnostics
            return result

    def _host_facts(self):
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
        if not result.returncode:
            code = "native_windows_host_facts_invalid"
            detail = "Native Windows host facts are not valid JSON."
            recovery = "Repair the host-facts probe output and retry; it must describe Windows, an absolute home and a boolean admin field."
            try:
                facts = json.loads(result.stdout)
            except ValueError:
                pass
            else:
                detail = "Native Windows host facts have an invalid schema."
                if (
                    isinstance(facts, dict)
                    and facts.get("os") == "Windows"
                    and type(facts.get("admin")) is bool
                    and isinstance(facts.get("home"), str)
                    and PureWindowsPath(facts["home"]).is_absolute()
                    and facts.get("shell") == "powershell.exe"
                    and all(isinstance(facts.get(key), str) and facts[key]
                            for key in ("edition", "build", "user"))
                    and facts["build"].isascii() and facts["build"].isdigit()
                ):
                    if facts["admin"] is False:
                        self.windows_facts = facts
                        return facts
                    code = "native_windows_test_user_required"
                    detail = "Native Windows QA requires a standard Windows SSH user; this token is an administrator."
                    recovery = "Select the provisioned standard test user and retry; do not grant it administrator privileges."
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

            return desktop_script(self, script, timeout=timeout)
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
            raise RuntimeError(
                "windows_host_file_read_failed: repair the declared file's ACL and retry"
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
