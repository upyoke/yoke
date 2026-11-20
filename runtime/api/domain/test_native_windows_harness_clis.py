"""Exercise vendor installer decoding in actual Windows PowerShell 5.1."""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import shutil
import subprocess
from threading import Thread
from uuid import uuid4

import pytest

from yoke_contracts.harness_cli_releases import VERSION_TOKEN_PATTERN
from yoke_harness.native_windows import harness_clis
from yoke_harness.native_windows.harness_clis import host_program
from yoke_harness.native_windows.transport import quote

pytestmark = pytest.mark.windows


@pytest.mark.windows_only(reason="requires Windows PowerShell 5.1")
@pytest.mark.parametrize("harness", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("media_type", ["application/octet-stream", "text/plain; charset=utf-8"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "invalid-utf-8"])
def test_vendor_installers_decode_raw_utf8(tmp_path, monkeypatch, harness, media_type, encoding):
    powershell = shutil.which("powershell.exe")
    assert powershell, "Windows PowerShell 5.1 is required for the regression"
    # This regression owns real PowerShell decoding. Desktop routing and token
    # behavior have separate coverage; the synthetic fixture has no user desktop.
    monkeypatch.setattr(
        harness_clis, "desktop_script", lambda control, script, *, timeout: control._run(script, timeout=timeout),
    )
    marker = tmp_path / "installed.txt"
    expected = "installer executed: café 雪"
    source = (
        "param([string]$Release)\n"
        + ("if($env:CODEX_NON_INTERACTIVE -ne '1' -or $Release -ne '1.2.3'){throw 'Missing pinned install'}\n"
           if harness == "codex" else "")
        +
        f"[IO.File]::WriteAllText({quote(str(marker))},{quote(expected)},"
        "[Text.UTF8Encoding]::new($false)); $global:LASTEXITCODE=0\n"
    ).encode("utf-8-sig" if encoding == "utf-8-sig" else "utf-8")
    if encoding == "invalid-utf-8":
        source = b"\xff" + source
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(source)))
            self.end_headers()
            self.wfile.write(source)

        def log_message(self, *_args):
            pass

    cli = tmp_path / "native-cli.cmd"
    cli.write_bytes(b"@echo off\r\necho native-cli 1.2.3\r\nexit /b 0\r\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    local_url = f"http://127.0.0.1:{server.server_port}/installer.ps1"
    vendor_url = {
        "claude-code": "https://claude.ai/install.ps1",
        "codex": "https://chatgpt.com/codex/install.ps1",
        "cursor": "https://cursor.com/install?win32=true",
    }[harness]
    content_type = "System.Byte[]" if media_type == "application/octet-stream" else "System.String"

    class Control:
        def _run(self, script, *, timeout):
            # Redirect only this vendor URL to the synthetic HTTP response. The
            # actual PowerShell web cmdlet still supplies Content/RawContentStream.
            prelude = fr"""$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
if($PSVersionTable.PSVersion.Major -ne 5){{throw 'Windows PowerShell 5.1 required'}}
function Invoke-WebRequest {{
 [CmdletBinding()]
 param([Parameter(Position=0)][string]$Uri,[switch]$UseBasicParsing,[int]$TimeoutSec)
 if($Uri -ne {quote(vendor_url)}){{throw 'Unexpected installer URL'}}
 $response=Microsoft.PowerShell.Utility\Invoke-WebRequest -UseBasicParsing -Uri {quote(local_url)} -TimeoutSec 10
 if($response.Content.GetType().FullName -ne {quote(content_type)}){{throw 'Unexpected web response Content type'}}
 $response
}}
"""
            encoded = base64.b64encode((prelude + script).encode("utf-16le")).decode("ascii")
            return subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )

    try:
        if encoding == "invalid-utf-8":
            with pytest.raises(RuntimeError, match="windows_vendor_installer_utf8_invalid"):
                host_program(
                    Control(), "install", [harness, [str(cli)], "", "1.2.3"], 30, VERSION_TOKEN_PATTERN,
                )
            assert not marker.exists()
        else:
            result = host_program(
                Control(), "install", [harness, [str(cli)], "", "1.2.3"], 30, VERSION_TOKEN_PATTERN,
            )
            assert result["install_exit_code"] == 0
            assert result["probe"]["version"] == "1.2.3"
            assert marker.read_text(encoding="utf-8") == expected
        assert requests == ["/installer.ps1"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.windows_only(reason="requires Windows PowerShell 5.1 and HKCU registry")
@pytest.mark.parametrize("exit_code,already_present", [(0, False), (0, True), (1, False)])
def test_claude_finishes_path_without_later_installers(tmp_path, exit_code, already_present):
    powershell = shutil.which("powershell.exe")
    assert powershell
    directory = tmp_path / ".local" / "bin"
    directory.mkdir(parents=True)
    executable = directory / "claude.exe"
    registry_path = "Software\\YokeQaTests\\" + uuid4().hex
    raw = r"%USERPROFILE%\keep;C:\existing"
    initial = raw + (";" + str(directory) if already_present else "")
    expected = initial if exit_code else raw + ";" + str(directory)

    class Control:
        def _run(self, script, *, timeout):
            # Exercise the real registry API in an owned test key. Never edit
            # this CI user's actual Environment key or depend on vendor access.
            script = script.replace("CreateSubKey('Environment')", f"CreateSubKey({quote(registry_path)})")
            prelude = f"""$ErrorActionPreference='Stop';$env:USERPROFILE={quote(str(tmp_path))}
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -TypeDefinition 'public class Cli {{public static void Main() {{System.Console.WriteLine("1.2.3");}}}}' -OutputAssembly {quote(str(executable))} -OutputType ConsoleApplication
$key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey({quote(registry_path)})
$key.SetValue('Path',{quote(initial)},[Microsoft.Win32.RegistryValueKind]::ExpandString);$key.Dispose()
function Invoke-WebRequest {{
 [CmdletBinding()]param($Uri,[switch]$UseBasicParsing,$TimeoutSec)
 @{{RawContentStream=[IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes('$global:LASTEXITCODE={exit_code}'))}}
}}
try {{
"""
            checks = f"""
 $key=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey({quote(registry_path)})
 try {{
  if($key.GetValue('Path','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) -cne {quote(expected)}){{throw 'PATH entries changed or duplicated'}}
  if($key.GetValueKind('Path') -ne [Microsoft.Win32.RegistryValueKind]::ExpandString){{throw 'PATH kind changed'}}
 }}finally{{$key.Dispose()}}
}}finally{{[Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree({quote(registry_path)})}}
"""
            encoded = base64.b64encode((prelude + script + checks).encode("utf-16le")).decode("ascii")
            return subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )

    result = host_program(
        Control(), "install", ["claude-code", [str(executable)], "", "1.2.3"], 30, VERSION_TOKEN_PATTERN,
    )
    assert result["install_exit_code"] == exit_code
    assert result["probe"]["version"] == "1.2.3"
