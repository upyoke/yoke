"""PowerShell framing and literal paths for Windows OpenSSH."""

import base64
import json
import subprocess
import time
from contextlib import contextmanager
from uuid import uuid4
from pathlib import PureWindowsPath
from types import SimpleNamespace

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows.stdin_frame import (
    frame_bytes,
    upload_script,
    upload_received,
)
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
        with self._staged_payload(command.encode("utf-8-sig")) as path:
            return super()._run(
                f"& {path}", input_text=input_text, timeout=timeout, debug_log=debug_log,
            )

    @contextmanager
    def _staged_payload(self, payload):
        name = "yoke-qa-" + uuid4().hex + ".ps1"
        path = f"(Join-Path $env:TEMP {quote(name)})"
        failure = None
        try:
            self._upload_chunks(path, payload)
            yield path
        except BaseException as exc:
            failure = exc
            raise
        finally:
            removed = super()._run(
                f"Remove-Item -LiteralPath {path} -Force -ErrorAction SilentlyContinue; if(Test-Path -LiteralPath {path}){{throw 'owned staging cleanup failed'}}",
                timeout=10,
            )
            if removed.returncode:
                if failure is not None:
                    failure.add_note("Owned Windows staging cleanup failed; remove the owned staging file before retrying.")
                else:
                    raise HostControlLocalError(
                        code="native_windows_staging_cleanup_failed", phase="script_cleanup",
                        detail="Owned Windows staging cleanup failed.",
                        recovery_hint="Remove the owned staging file before retrying.",
                        exit_code=removed.returncode, stderr=removed.stderr,
                        secrets=getattr(self, "secret_values", ()),
                    )

    def _upload_chunks(self, path, payload):
        # Native Windows ssh can stall on a monolithic stdin write. Reuse the
        # provisioner's bounded frames and cumulative length/hash receipts.
        deadline = time.monotonic() + 30
        for offset in range(0, len(payload), 2048):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("windows_script_upload_failed: bounded upload timed out; retry the complete upload")
            chunk = payload[offset:offset + 2048]
            uploaded = super()._run(
                upload_script(path, offset=offset), input_text=frame_bytes(chunk), timeout=remaining,
            )
            if not upload_received(uploaded, payload[:offset + len(chunk)]):
                raise HostControlLocalError(
                    code="windows_script_upload_failed", phase="script_upload",
                    detail="Windows upload length/hash receipt did not match.",
                    recovery_hint="Repair the named SSH upload error and retry the complete upload before execution.",
                    exit_code=uploaded.returncode, stdout=uploaded.stdout, stderr=uploaded.stderr,
                    secrets=getattr(self, "secret_values", ()),
                )

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
        if len(content) > 2048:
            with self._staged_payload(content) as staging:
                result = super()._run(
                    f"New-Item -ItemType Directory -Force (Split-Path {quote(path)}) | Out-Null; Move-Item -LiteralPath {staging} -Destination {quote(path)} -Force",
                )
                if result.returncode:
                    raise HostControlLocalError(
                        code="windows_host_file_write_failed", phase="file_commit",
                        detail="Verified Windows upload could not be committed.",
                        recovery_hint="Repair the destination directory or file ACL and retry.",
                        exit_code=result.returncode, stderr=result.stderr,
                        secrets=getattr(self, "secret_values", ()),
                    )
            return True
        data = frame_bytes(content)
        result = self._run(
            upload_script(quote(path)),
            input_text=data,
        )
        if not upload_received(result, content):
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
