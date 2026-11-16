"""PowerShell framing and literal paths for Windows OpenSSH."""

import base64
import json
import subprocess
from uuid import uuid4
from pathlib import PureWindowsPath
from types import SimpleNamespace

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


def quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


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
        name = "yoke-qa-" + uuid4().hex + ".ps1"
        path = f"(Join-Path $env:TEMP {quote(name)})"
        write = f"[IO.File]::WriteAllBytes({path},[Convert]::FromBase64String([Console]::In.ReadToEnd()))"
        uploaded = super()._run(
            write,
            input_text=base64.b64encode(command.encode("utf-8-sig")).decode("ascii"),
            timeout=30,
        )
        if uploaded.returncode:
            return uploaded
        return super()._run(
            f"try {{ & {path} }} finally {{ Remove-Item -LiteralPath {path} -Force }}",
            input_text=input_text,
            timeout=timeout,
            debug_log=debug_log,
        )

    def _host_facts(self):
        result = self._run(
            r"""$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$admin=([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole('Administrators')
$os=Get-CimInstance Win32_OperatingSystem
@{home=$env:USERPROFILE;shell='powershell.exe';os='Windows';admin=$admin;
  edition=$os.Caption;build=$os.BuildNumber;user=$identity.Name} | ConvertTo-Json -Compress
""",
            timeout=20,
        )
        try:
            facts = json.loads(result.stdout)
            valid = (
                facts["os"] == "Windows"
                and not facts["admin"]
                and PureWindowsPath(facts["home"]).is_absolute()
            )
        except (ValueError, KeyError, TypeError):
            valid = False
        if result.returncode or not valid:
            raise HostControlLocalError(
                code="native_windows_test_user_required",
                phase="host_facts_ssh",
                detail="Native Windows QA requires a standard Windows SSH user.",
                recovery_hint="Provision Windows OpenSSH and its standard test user; verify the authorized key and retry.",
            )
        self.windows_facts = facts
        return facts

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
        data = base64.b64encode(content).decode("ascii")
        result = self._run(
            f"$p={quote(path)}; New-Item -ItemType Directory -Force (Split-Path $p) | Out-Null; "
            "[IO.File]::WriteAllBytes($p,[Convert]::FromBase64String([Console]::In.ReadToEnd()))",
            input_text=data,
        )
        if result.returncode:
            raise RuntimeError(
                "windows_host_file_write_failed: repair the declared file's ACL and retry"
            )
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
