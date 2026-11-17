"""TEMPORARY diagnostic: end this xdist worker the way the old SIGTERM test did."""
import os
import signal


def test_kill_own_worker():
    os.kill(os.getpid(), signal.SIGTERM)
