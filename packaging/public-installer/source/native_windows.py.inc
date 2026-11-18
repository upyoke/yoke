def candidate_python(generation: Path) -> Path:
    environment = generation / "tools" / "yoke-cli"
    if sys.platform == "win32":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python3"


def windows_long_paths_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as handle:
            return winreg.QueryValueEx(handle, "LongPathsEnabled")[0] == 1
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise InstallError(
            f"windows_long_paths_unreadable: {exc}; ask your administrator to "
            r"check HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled "
            "and rerun the installer."
        ) from exc


def long_path_refusal() -> InstallError:
    return InstallError(
        "windows_long_paths_disabled: installation needs a path longer than "
        "260 characters. Ask your administrator to set DWORD LongPathsEnabled=1 "
        r"in HKLM\SYSTEM\CurrentControlSet\Control\FileSystem, restart Windows, "
        "then rerun the installer; or use shorter UV_TOOL_DIR and UV_CACHE_DIR paths."
    )


def require_windows_path(path: Path) -> None:
    if sys.platform == "win32" and len(str(path.absolute())) >= 260:
        if not windows_long_paths_enabled():
            raise long_path_refusal()


UNTRUSTED_MOUNT_POINT_REFUSAL = (
    "windows_untrusted_mount_point: uv could not follow the Python link "
    "directory it just created (os error 448, untrusted mount point). Windows "
    "Redirection Guard blocks this process from following directory junctions; "
    "OpenSSH sessions run under it. See https://github.com/astral-sh/uv/issues/19616. "
    "Run the installer from a local PowerShell window on this computer, not over SSH."
)


def refuse_untrusted_mount_point(result) -> None:
    if sys.platform != "win32":
        return
    if "os error 448" in ((result.stdout or "") + "\n" + (result.stderr or "")):
        raise InstallError(UNTRUSTED_MOUNT_POINT_REFUSAL)


def refuse_windows_path_failure(result) -> None:
    if sys.platform != "win32":
        return
    refuse_untrusted_mount_point(result)
    diagnostic = (result.stdout + "\n" + result.stderr).lower()
    if any(word in diagnostic for word in ("filename or extension is too long", "os error 206", "winerror 206", "path too long")):
        if not windows_long_paths_enabled():
            raise long_path_refusal()
