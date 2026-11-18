"""Embed the shared stdlib platform boundaries on hosts without Yoke installed."""
import inspect
from pathlib import Path

from yoke_contracts import platform_file_lock
from yoke_contracts.owner_private_path import posix_uid
from yoke_contracts.platform_process import detach_current_process, spawn_group_process


def source() -> str:
    helpers = "\n".join(inspect.getsource(function) for function in
                        (posix_uid, detach_current_process, spawn_group_process))
    lock_source = Path(platform_file_lock.__file__).read_text(encoding="utf-8")
    return ("import os, subprocess\n" + helpers
            + "\n_platform_lock = {}\n"
            + f"exec(compile({lock_source!r}, '<platform_file_lock>', 'exec'), _platform_lock)\n"
            + "acquire_exclusive = _platform_lock['acquire_exclusive']\n")
