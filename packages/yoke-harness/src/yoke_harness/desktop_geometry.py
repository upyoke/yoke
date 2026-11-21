"""Minimum usable remote desktop geometry shared by Test Machine adapters."""

MINIMUM_WIDTH = 1920
MINIMUM_HEIGHT = 1080
MINIMUM_RESOLUTION = f"{MINIMUM_WIDTH}x{MINIMUM_HEIGHT}"


def is_desktop_resolution(value):
    """Validate the measured width and height in a fixture receipt."""
    if not isinstance(value, str):
        return False
    width, _, height = value.partition("x")
    return (
        width.isascii() and width.isdecimal() and len(width) <= 5
        and height.isascii() and height.isdecimal() and len(height) <= 5
        and MINIMUM_WIDTH <= int(width) <= 16384
        and MINIMUM_HEIGHT <= int(height) <= 16384
    )
