"""Executable and import directories owned by a Python virtual environment."""

from pathlib import Path
import os
import sys


def venv_scripts(root: Path) -> Path:
    """Directory containing this platform's venv executables."""
    return Path(root) / ("Scripts" if os.name == "nt" else "bin")


def venv_python(root: Path, *, name: str = "python") -> Path:
    """Interpreter path; Windows uses python.exe for either POSIX spelling."""
    return venv_scripts(root) / ("python.exe" if os.name == "nt" else name)


def venv_console_script(root: Path, name: str, *, windows_suffix: str = ".exe") -> Path:
    """Installed console script, or a declared Windows command shim."""
    return venv_scripts(root) / (name + windows_suffix if os.name == "nt" else name)


def venv_site_packages(root: Path) -> Path:
    """Pure Python package directory for an environment of this interpreter."""
    if os.name == "nt":
        return Path(root) / "Lib" / "site-packages"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return Path(root) / "lib" / version / "site-packages"
