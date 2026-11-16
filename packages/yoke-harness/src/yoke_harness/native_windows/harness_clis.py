"""Native vendor installers and probes; never execute a POSIX installer."""

import json

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
        installers = {
            "claude-code": "& ([ScriptBlock]::Create((Invoke-WebRequest -UseBasicParsing 'https://claude.ai/install.ps1').Content)) "
            + quote(wanted),
            "codex": "& npm.cmd install --global " + quote("@openai/codex@" + wanted),
            "cursor": "& ([ScriptBlock]::Create((Invoke-WebRequest -UseBasicParsing 'https://cursor.com/install?win32=true').Content))",
        }
        script += installers[harness] + "; $code=$LASTEXITCODE; $p=Probe $payload[1]; "
        script += "@{install_exit_code=$code;install_stderr='';probe=$p} | ConvertTo-Json -Depth 8 -Compress"
    result = control._run(script, timeout=timeout)
    if result.returncode:
        raise RuntimeError(
            "windows_harness_cli_failed: repair the native vendor installer and PATH, then retry; "
            + result.stderr[-600:]
        )
    return json.loads(result.stdout.strip().splitlines()[-1])
