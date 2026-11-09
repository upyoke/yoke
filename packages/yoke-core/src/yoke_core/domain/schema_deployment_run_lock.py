"""Bounded deployment-run and additive schema lock timeout."""

#: How long a caller lets the run row settle before refusing. Long enough to
#: ride out an ordinary concurrent mutation, far short of any client's
#: response timeout, so the refusal reaches a caller that is still listening.

RUN_ROW_LOCK_TIMEOUT_MS = 2000
