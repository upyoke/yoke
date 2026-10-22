"""Shared teaching-file size limits."""
WIDTH = 80
LINE_LIMIT = 350


def wrapped_lines(text):
    return sum(max(1, -(-len(line) // WIDTH)) for line in text.splitlines())
