"""Finish CLI output quietly when a pipe reader has closed stdout."""

from functools import wraps
import os
import sys


class _StdoutClosed(BrokenPipeError):
    """A pipe error identified at the stdout write or flush boundary."""


class _StdoutWriter:
    def __init__(self, stream):
        self.stream = stream

    def write(self, value):
        try:
            return self.stream.write(value)
        except BrokenPipeError as exc:
            raise _StdoutClosed() from exc

    def flush(self):
        try:
            return self.stream.flush()
        except BrokenPipeError as exc:
            raise _StdoutClosed() from exc

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        value = getattr(self.stream, name)
        return _StdoutWriter(value) if name == "buffer" else value


def quiet_closed_stdout(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        original = sys.stdout
        output = _StdoutWriter(original)
        sys.stdout = output
        try:
            result = operation(*args, **kwargs)
            output.flush()
            return result
        except _StdoutClosed:
            # Prevent the interpreter's final buffered flush from raising again.
            try:
                with open(os.devnull, "w") as sink:
                    os.dup2(sink.fileno(), original.fileno())
            except (OSError, ValueError):
                pass
            return 0
        finally:
            sys.stdout = original

    return run
