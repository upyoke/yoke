"""Bounded failure evidence for the actual Windows offset-frame probe."""

import hashlib
import json
import shutil
import subprocess
import time

from yoke_harness.native_windows.stdin_frame import frame_bytes, upload_script
from yoke_harness.native_windows.transport import encoded, quote


def chunk_probe(target, chunk, offset):
    executable = shutil.which("powershell.exe")
    assert executable, "Windows PowerShell executable missing"
    script = upload_script(quote(str(target)), offset=offset)
    # These markers change no frame/file operation and use stderr so the
    # producer's exact length/hash receipt remains the only success evidence.
    for before, after in (
        ("$bytes=Read-YokeFrame", "[Console]::Error.WriteLine('YOKE_CHUNK_PHASE:read_begin'); $bytes=Read-YokeFrame; [Console]::Error.WriteLine('YOKE_CHUNK_PHASE:read_done')"),
        ("$file=[IO.File]::Open", "[Console]::Error.WriteLine('YOKE_CHUNK_PHASE:open'); $file=[IO.File]::Open"),
        ("$file.Write($bytes,0,$bytes.Length)", "$file.Write($bytes,0,$bytes.Length); [Console]::Error.WriteLine('YOKE_CHUNK_PHASE:written')"),
        ("Write-Output ('YOKE_UPLOAD:'", "[Console]::Error.WriteLine('YOKE_CHUNK_PHASE:hash_done'); Write-Output ('YOKE_UPLOAD:'"),
    ):
        assert before in script
        script = script.replace(before, after, 1)
    script = "[Console]::Error.WriteLine('YOKE_CHUNK_PHASE:entered version='+$PSVersionTable.PSVersion.ToString()); " + script
    script += "\n[Console]::Error.WriteLine('YOKE_CHUNK_PHASE:finished')"
    started = time.monotonic()
    try:
        return subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded(script)],
            input=frame_bytes(chunk), capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired as error:
        evidence = {"executable": executable, "offset": offset, "payload_bytes": len(chunk),
                    "elapsed": round(time.monotonic() - started, 3)}
        for name in ("stdout", "stderr"):
            value = getattr(error, name) or ""
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="backslashreplace")
            evidence[name] = value[-2400:]
        try:
            evidence["target_exists"] = target.exists()
            if target.exists():
                evidence["target_length"] = target.stat().st_size
                evidence["target_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as failure:
            evidence["target_inspection_error"] = type(failure).__name__
        error.add_note("native_chunk_probe_diagnostic: " + json.dumps(evidence))
        raise
