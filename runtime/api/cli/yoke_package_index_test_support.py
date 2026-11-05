# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

import re

import subprocess

import zipfile

from pathlib import Path

from urllib.parse import quote

import pytest

from runtime.api.cli.release_fixture_helpers import sample_release as _sample_release

from yoke_core.tools import distribution_publish, package_index, release_artifacts


def _record(records: list[dict[str, object]], project: str) -> dict[str, object]:
    return next(entry for entry in records if entry["project"] == project)
