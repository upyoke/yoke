"""Canonical machine launcher locations."""
from typing import Tuple

TARGET_PRIORITY: Tuple[Tuple[str, str], ...] = (
    ("/opt/homebrew/bin", "homebrew_apple_silicon"),
    ("/usr/local/bin", "homebrew_intel_or_linux"),
    ("~/.local/bin", "fallback_user_local"),
)



LAUNCHER_FILENAME = "yoke"

