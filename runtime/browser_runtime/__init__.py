"""Packaged Browser QA runtime sources.

This package carries the Node.js daemon sources (``src/``), their unit
tests (``tests/``), and the npm manifests (``package.json`` /
``package-lock.json``) that back Yoke's Browser QA substrate. Nothing
executes from here directly: ``yoke_core.domain.browser_runtime_home``
materializes these files into the machine-level runtime directory
(``~/.yoke/browser-runtime/``), where npm dependencies, Playwright
browsers, and daemon state live. Project repos never receive a copy.
"""
