"""Run an installed Yoke command on native Windows without cmd.exe parsing.

The installer's one-line ``yoke.cmd`` shim names Python and its launcher.
Calling it hands every argument to cmd.exe, which reparses quotes, ``&`` and
``%`` -- a JSON argument does not survive. This script reads the shim on the
host and starts that Python and its stdlib-only launcher directly (``-I -S``,
as the shim does) with the Windows argv contract, so arguments arrive exactly
as given.
"""

import subprocess
from pathlib import PureWindowsPath

from yoke_contracts.windows_powershell import quote, yoke_shim_process_info

_YOKE_NAMES = frozenset({"yoke", "yoke.cmd"})
# Commands that show a page: the identity launcher and the managed browser.
_PAGE_COMMANDS = (("browser", "open"), ("qa", "browser"))


def opens_identity_page(argv) -> bool:
    """Whether *argv* is a Yoke command that shows a browser page."""
    words = [str(word) for word in argv]
    return (
        len(words) >= 3
        and PureWindowsPath(words[0]).name.lower() in _YOKE_NAMES
        and tuple(words[1:3]) in _PAGE_COMMANDS
    )


def yoke_python_command(argv) -> str:
    """The PowerShell script running ``argv`` (``[yoke.cmd path or yoke, *arguments]``).

    A bare ``yoke`` resolves the shim on the user's ``PATH``.
    """
    shim, arguments = str(argv[0]), list(argv[1:])
    locate = (
        quote(shim)
        if PureWindowsPath(shim).is_absolute()
        else "(Get-Command yoke.cmd -ErrorAction SilentlyContinue).Source"
    )
    argv = quote(subprocess.list2cmdline(arguments))
    return f"""{yoke_shim_process_info(locate, argv)}
$info.UseShellExecute=$false
$info.RedirectStandardOutput=$true
$info.RedirectStandardError=$true
$p=[Diagnostics.Process]::new(); $p.StartInfo=$info
if(!$p.Start()){{throw 'windows_process_start_failed: repair the installed Yoke Python and retry'}}
$out=$p.StandardOutput.ReadToEndAsync(); $err=$p.StandardError.ReadToEndAsync()
$p.WaitForExit()
[Console]::Out.Write($out.Result); [Console]::Error.Write($err.Result)
$code=$p.ExitCode; $p.Dispose(); exit $code
"""


__all__ = ["opens_identity_page", "yoke_python_command"]
