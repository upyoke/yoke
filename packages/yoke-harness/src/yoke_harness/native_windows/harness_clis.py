"""Native vendor installers and probes; never execute a POSIX installer."""

import json

from yoke_harness.native_windows.desktop import desktop_script
from yoke_harness.native_windows.transport import quote


def host_program(control, action, payload, timeout, pattern):
    probe = r"""function Probe($names) {
 $tool=$null
 foreach($name in $names){$tool=Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1; if($tool){break}}
 if(!$tool){return @{version=$null;exit_code=$null;stderr='CLI missing from native PATH';executable=$null}}
 $text=(& $tool.Source --version 2>&1 | Out-String); $code=$LASTEXITCODE
 $version=if($code -eq 0 -and $text -match PATTERN){$Matches[0]}else{$null}
 return @{version=$version;exit_code=$code;stderr=if($version){''}else{$text};executable=$tool.Source}
}
$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
""".replace("PATTERN", quote(pattern))
    script = probe + "$payload=ConvertFrom-Json " + quote(json.dumps(payload)) + "; "
    if action == "probe":
        script += "$out=@{}; foreach($row in $payload){$p=Probe $row[1]; $out[$row[0]]=if($p.version){$p.version}else{$p}}; $out | ConvertTo-Json -Depth 8 -Compress"
    else:
        harness, names, _, wanted = payload
        # Windows PowerShell returns byte[] Content for application/octet-stream.
        # Decode the raw response identically for binary and text media types.
        script += r"""function VendorScript($uri) {
 $response=Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec 30 -ErrorAction Stop
 $bytes=$response.RawContentStream.ToArray()
 try { $text=([Text.UTF8Encoding]::new($false,$true)).GetString($bytes).TrimStart([char]0xFEFF) }
 catch { throw 'windows_vendor_installer_utf8_invalid: inspect the vendor raw response encoding before retrying; installer not executed' }
 [ScriptBlock]::Create($text)
}
"""
        installers = {
            "claude-code": "& (VendorScript 'https://claude.ai/install.ps1') "
            + quote(wanted),
            "codex": "& npm.cmd install --global " + quote("@openai/codex@" + wanted),
            "cursor": "& (VendorScript 'https://cursor.com/install?win32=true')",
        }
        script += installers[harness] + "; $code=$LASTEXITCODE; "
        if harness == "claude-code":
            # Claude's native installer reports success while only warning that
            # .local\bin is absent from PATH. Finish this installer immediately,
            # independently of any later vendor installation.
            script += r"""if($code -eq 0){
 $dir=Join-Path $env:USERPROFILE '.local\bin';$exe=Join-Path $dir 'claude.exe'
 $installed=Probe @($exe)
 if($installed.version){
  $key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
  try {
   $raw=[string]$key.GetValue('Path','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
   $kind=if($key.GetValueNames() -contains 'Path'){$key.GetValueKind('Path')}else{[Microsoft.Win32.RegistryValueKind]::ExpandString}
   $entries=@($raw -split ';'|ForEach-Object {[Environment]::ExpandEnvironmentVariables($_).TrimEnd('\')})
   if($entries -inotcontains $dir){$key.SetValue('Path',($raw.TrimEnd(';')+';'+$dir).TrimStart(';'),$kind)}
  } finally {$key.Dispose()}
  $env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
 }
}
"""
        script += "$p=Probe $payload[1]; "
        script += "@{install_exit_code=$code;install_stderr='';probe=$p} | ConvertTo-Json -Depth 8 -Compress"
    # Cursor's architecture query needs the same user's interactive logon token;
    # the standard SSH token can be denied local CIM/WMI access. The desktop
    # helper refuses absent sessions and never substitutes an elevated token.
    if action == "install" and payload[0] == "cursor":
        result = desktop_script(control, script, timeout=timeout)
    else:
        result = control._run(script, timeout=timeout)
    if result.returncode:
        error = RuntimeError(
            "windows_harness_cli_failed: repair the native vendor installer and PATH, then retry; "
            + result.stderr[-600:]
        )
        error.primary_result = result
        for name in ("desktop_diagnostics", "staging_diagnostics"):
            if hasattr(result, name):
                setattr(error, name, getattr(result, name))
        raise error
    return json.loads(result.stdout.strip().splitlines()[-1])
