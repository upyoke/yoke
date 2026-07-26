"""Dependency-free step identifiers for the onboarding wizard."""

from __future__ import annotations

STEP_INSTALL = "install"
STEP_CONNECT = "connect"
STEP_PROJECT = "project"
STEP_GITHUB = "github"
STEP_HOSTING = "hosting"
STEP_FINISH = "finish"

__all__ = [
    "STEP_CONNECT",
    "STEP_FINISH",
    "STEP_GITHUB",
    "STEP_HOSTING",
    "STEP_INSTALL",
    "STEP_PROJECT",
]
