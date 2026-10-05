"""Finish CLI output quietly when a pipe reader has closed stdout."""

from functools import wraps
import os
import sys


def quiet_closed_stdout(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        try:
            result = operation(*args, **kwargs)
            sys.stdout.flush()
            return result
        except BrokenPipeError:
            # Prevent the interpreter's final buffered flush from raising again.
            try:
                with open(os.devnull, "w") as sink:
                    os.dup2(sink.fileno(), sys.stdout.fileno())
            except (OSError, ValueError):
                pass
            return 0

    return run
