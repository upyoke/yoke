"""Probe the pinned Windows engine's Unix sockets before choosing transport."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import urllib.request


def run(argv, *, check=True):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    print(result.stdout, result.stderr, flush=True)
    if check:
        result.check_returncode()
    return result


def main():
    assert os.name == "nt", "This probe requires native Windows"
    work = Path(tempfile.mkdtemp(prefix="Yoke profile with spaces "))
    asset = "postgresql-17.11.1-x86_64-pc-windows-msvc.tar.gz"
    url = f"https://github.com/theseus-rs/postgresql-binaries/releases/download/17.11.1/{asset}"
    archive = work / asset
    urllib.request.urlretrieve(url, archive)
    checksum = urllib.request.urlopen(url + ".sha256").read().decode().split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == checksum
    with tarfile.open(archive) as stream:
        stream.extractall(work / "engine", filter="tar")
    binary = next((work / "engine").rglob("initdb.exe")).parent
    import pefile
    for image in [binary / "initdb.exe", binary / "libpq.dll"]:
        pe = pefile.PE(str(image))
        print(image.name, "imports:", [entry.dll.decode() for entry in pe.DIRECTORY_ENTRY_IMPORT], flush=True)
    import ctypes
    for dll in binary.glob("*.dll"):
        try:
            ctypes.WinDLL(str(dll))
        except OSError as exc:
            print("DLL load failure:", dll.name, exc, flush=True)
    os.environ["PATH"] = str(binary) + os.pathsep + str(binary / "DLLs") + os.pathsep + str(binary.parent / "lib") + os.pathsep + os.environ["PATH"]
    root = work / "private cluster"
    root.mkdir()
    owner = run(["whoami"]).stdout.strip()
    run(["icacls", str(root), "/inheritance:r", "/grant:r", f"{owner}:(OI)(CI)F"])
    sock = root / "sock"
    sock.mkdir()
    data = root / "data"
    run([str(binary / "initdb.exe"), "-D", str(data), "-U", "probe", "--auth=trust", "--locale=C"])
    # PostgreSQL's server option parser needs quotes around the path with spaces.
    options = f'-k "{sock.as_posix()}" -c listen_addresses=\'\''
    try:
        result = run([str(binary / "pg_ctl.exe"), "-D", str(data), "-l", str(root / "server.log"), "-o", options, "-w", "start"], check=False)
        if result.returncode:
            print((root / "server.log").read_text(errors="replace"))
            raise RuntimeError("windows_unix_socket_unavailable: pinned engine cannot start owner-private Unix socket")
        run([str(binary / "psql.exe"), "-h", sock.as_posix(), "-U", "probe", "-d", "postgres", "-Atc", "SELECT 1"])
        print("WINDOWS_UNIX_SOCKET_OWNER_CONNECTION_PASSED", flush=True)
    finally:
        run([str(binary / "pg_ctl.exe"), "-D", str(data), "-m", "immediate", "stop"], check=False)


if __name__ == "__main__":
    main()
