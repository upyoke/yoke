"""Measure and size the real XFCE display, including an unattended session."""

if __package__:
    from yoke_harness.desktop_geometry import MINIMUM_HEIGHT, MINIMUM_RESOLUTION, MINIMUM_WIDTH

import os
import re
import subprocess

_XRDP_FULL_HD_MODE = "YokeQa-1920x1080"
_FULL_HD_TIMING = (
    "148.50", "1920", "2008", "2052", "2200", "1080", "1084", "1089", "1125",
    "+hsync", "+vsync",
)


def _display_command(environment, *argv):
    try:
        result = subprocess.run(
            argv, env={**os.environ, **environment}, capture_output=True,
            text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"linux_desktop_geometry_unavailable: {argv[0]} failed ({type(exc).__name__}); "
            "repair the XFCE display tools and retry"
        ) from None
    if result.returncode:
        raise RuntimeError(
            f"linux_desktop_geometry_unavailable: {argv[0]}: {result.stderr.strip()}; "
            "inspect the fixture display, then sign out and retry to start a full-HD desktop"
        )
    return result.stdout


def _display_geometry(environment):
    info = _display_command(environment, "xwininfo", "-root")
    values = re.findall(r"^\s*(?:Width|Height|Depth):\s*(\d+)\s*$", info, re.MULTILINE)
    if len(values) != 3:
        raise RuntimeError(
            "linux_desktop_geometry_invalid: repair xwininfo on the fixture display and retry"
        )
    return tuple(int(value) for value in values)


def _resize_display(environment):
    layout = _display_command(environment, "xrandr", "--query")
    outputs = re.findall(r"^(\S+) connected ", layout, re.MULTILINE)
    if len(outputs) != 1:
        return
    [output] = outputs
    mode = MINIMUM_RESOLUTION
    modes = re.findall(r"^ +([^\s]+) +\d", layout, re.MULTILINE)
    if mode not in modes and output == "rdp0":
        # xorgxrdp advertises only the negotiated size until a new mode is added.
        mode = _XRDP_FULL_HD_MODE
        if mode not in modes:
            _display_command(environment, "xrandr", "--newmode", mode, *_FULL_HD_TIMING)
            try:
                _display_command(environment, "xrandr", "--addmode", output, mode)
            except RuntimeError:
                _display_command(environment, "xrandr", "--rmmode", mode)
                raise
    _display_command(environment, "xrandr", "--output", output, "--mode", mode)


def desktop_geometry(environment, *, can_resize):
    width, height, depth = _display_geometry(environment)
    if can_resize and (width < MINIMUM_WIDTH or height < MINIMUM_HEIGHT):
        _resize_display(environment)
        width, height, depth = _display_geometry(environment)
    if width < MINIMUM_WIDTH or height < MINIMUM_HEIGHT:
        raise RuntimeError(
            f"linux_desktop_resolution_too_small: {width}x{height}; "
            f"set the fixture display to at least {MINIMUM_RESOLUTION}, "
            "or sign out and retry to start a full-HD desktop"
        )
    if width > 16384 or height > 16384 or depth not in {16, 24, 32}:
        raise RuntimeError(
            "linux_desktop_geometry_invalid: inspect the registered XFCE display before retrying"
        )
    return {"resolution": f"{width}x{height}", "depth": depth}
