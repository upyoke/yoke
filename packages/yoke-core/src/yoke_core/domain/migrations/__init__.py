"""Packaged governed-migration modules for remote engine installs.

Modules live here only while a governed cutover is still pending on at least
one installed engine database.  The ordinary source-checkout runner and hosted
fleet runner import the same implementation, so rehearsal and live apply
cannot drift across deployment modes.
"""
