"""Bounded ASCII stdin frames that do not depend on Windows OpenSSH sending EOF."""

import base64
import hashlib


MAX_BYTES = 64 * 1024 * 1024
MAX_ENCODED = 4 * ((MAX_BYTES + 2) // 3)


def frame_bytes(payload: bytes) -> str:
    if len(payload) > MAX_BYTES:
        raise ValueError("windows_stdin_frame_too_large: split the upload and retry")
    data = base64.b64encode(payload).decode("ascii")
    return f"{len(data):08x}:{data}"


# Read only the declared byte count. In particular, never probe for EOF after
# the frame: Windows OpenSSH may keep the redirected console stream open.
READ_FRAME_SCRIPT = r"""
function Read-YokeExact($stream,[int]$count){
 $buffer=New-Object byte[] $count
 $offset=0
 while($offset -lt $count){
  $read=$stream.Read($buffer,$offset,$count-$offset)
  if($read -eq 0){throw 'windows_stdin_frame_truncated: resend the complete frame'}
  $offset+=$read
 }
 return ,$buffer
}
function Read-YokeFrame {
 $stream=[Console]::OpenStandardInput()
 $header=[Text.Encoding]::ASCII.GetString((Read-YokeExact $stream 9))
 if($header -cnotmatch '\A[0-9a-f]{8}:\z'){throw 'windows_stdin_frame_header_invalid: resend a framed payload'}
 $count=[Convert]::ToInt64($header.Substring(0,8),16)
 if($count -gt MAX_ENCODED -or $count % 4 -ne 0){throw 'windows_stdin_frame_size_invalid: use a bounded base64 payload'}
 $raw=Read-YokeExact $stream ([int]$count)
 $data=[Text.Encoding]::ASCII.GetString($raw)
 $bytes=[Convert]::FromBase64String($data)
 if([Convert]::ToBase64String($bytes) -cne $data){throw 'windows_stdin_frame_encoding_invalid: use canonical base64'}
 return ,$bytes
}
""".replace("MAX_ENCODED", str(MAX_ENCODED))


def upload_script(path_expression: str) -> str:
    """The path expression must already be a quoted PowerShell literal/expression."""
    return (
        READ_FRAME_SCRIPT
        + f"""
$ErrorActionPreference='Stop'
$p={path_expression}
$bytes=Read-YokeFrame
New-Item -ItemType Directory -Force (Split-Path $p) | Out-Null
[IO.File]::WriteAllBytes($p,$bytes)
$stored=[IO.File]::ReadAllBytes($p)
$sha=[Security.Cryptography.SHA256]::Create()
try {{$digest=([BitConverter]::ToString($sha.ComputeHash($stored))).Replace('-','').ToLowerInvariant()}}
finally {{$sha.Dispose()}}
Write-Output ('YOKE_UPLOAD:'+ $stored.Length + ':' + $digest)
"""
    )


def upload_received(result, payload: bytes) -> bool:
    receipt = f"YOKE_UPLOAD:{len(payload)}:{hashlib.sha256(payload).hexdigest()}"
    return result.returncode == 0 and receipt in (result.stdout or "").splitlines()
