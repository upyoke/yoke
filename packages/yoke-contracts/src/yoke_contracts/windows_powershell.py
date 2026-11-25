"""PowerShell literals, encoded commands and Yoke shim invocation."""

import base64

SHIM_UNREADABLE = "windows_yoke_shim_unreadable"
_SHIM_PATTERN = r'^@(?:\(goto\) 2>nul & )?"([^"]+)" (?:-I -S )?"([^"]+)" %\*'

# PowerShell treats straight and typographic single quotes as delimiters.
_SINGLE_QUOTES = str.maketrans({quote: quote * 2 for quote in "'‘’‚‛"})


def quote(value: str) -> str:
    return "'" + str(value).translate(_SINGLE_QUOTES) + "'"


def encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def yoke_shim_process_info(shim_path: str, arguments_expression: str) -> str:
    """Set $info from a shim path and Windows argv expressions."""
    reason = quote(SHIM_UNREADABLE + ": ")
    recovery = quote(
        " is missing or is not the installer's yoke.cmd shim; reinstall Yoke, then rerun."
    )
    return (
        f"$shimPath={shim_path}; "
        "$shim=if($shimPath -and (Test-Path -LiteralPath $shimPath))"
        "{[IO.File]::ReadAllText($shimPath)}else{''}; "
        f"if($shim -notmatch {quote(_SHIM_PATTERN)})"
        f"{{[Console]::Error.Write({reason}+[string]$shimPath+{recovery}); exit 70}}; "
        "$info=[Diagnostics.ProcessStartInfo]::new(); $info.FileName=$Matches[1]; "
        f"""$info.Arguments='-I -S "'+$Matches[2]+'" '+{arguments_expression}"""
    )
