"""Shared teaching-file size limits.

Teaching files count 80-column wrapped lines against the Yoke source
repository's ``file_line_limit``.
"""
from yoke_contracts.project_contract.file_line_policy import project_limit

from model import TEACHING_ROOT

WIDTH = 80


def line_limit():
    return project_limit(TEACHING_ROOT.parents[1])


def wrapped_lines(text):
    return sum(max(1, -(-len(line) // WIDTH)) for line in text.splitlines())
