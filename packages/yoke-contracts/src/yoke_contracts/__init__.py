"""yoke_contracts — shared, zero-authority wire/file shapes + pure helpers.

The piece that lets the Yoke client and server agree on types *without the client
importing the server*. Contains the function-call envelope, API/CLI manifest +
install-bundle/manifest schemas, the machine-config schema shape, pure board-art
helpers, `.yoke/` scaffolds, and the hook-runner shared types/ordering.

May depend only on stdlib + pydantic (+ pyfiglet for ASCII art, optional Pillow for
image art). MUST NOT import `yoke_core`, `yoke_cli`, `yoke_harness`, or any
`runtime.api.*` / `runtime.harness.*` module.
"""
