"""Portable pipe deadlines and startup-to-turn reader handoff."""

import os

import pytest

from yoke_harness.session_relay_pipe_reader import PipeReader
pytestmark = pytest.mark.windows

def test_timeout_keeps_pipe_and_later_bytes_for_the_next_owner():
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as pipe:
        reader = PipeReader(pipe)
        try:
            with pytest.raises(TimeoutError):
                reader.read(timeout=0.01)
            os.write(write_fd, b'{"thread":"ready"}\n')
            assert reader.read(timeout=1) == b'{"thread":"ready"}\n'
            os.write(write_fd, b"turn content")
            os.close(write_fd)
            assert reader.read(timeout=1) == b"turn content"
            assert reader.read(timeout=1) == b""
            assert reader.read(timeout=0) == b""
        finally:
            reader.close()
