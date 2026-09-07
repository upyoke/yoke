# Selectable models are observed per machine, not compiled into the build

## What a hardcoded catalog actually said

Yoke carried a per-surface tuple of model ids and treated it as the answer to
"what can this account select". Checked against the installed CLIs on one
workstation, that tuple was wrong in both directions at once:

- The codex app-server published `gpt-6-astra` and `gpt-5.3-codex-spark`. The
  compiled list named neither, so two selectable models were invisible.
- The compiled list named `gpt-5.4`. The app-server had no such model; it had
  `gpt-5.4-mini`, already carrying an upgrade target of `gpt-5.6-luna` and a
  retirement date.
- Cursor published 211 selectable tokens. The compiled list for that surface
  was empty, and the only reason Cursor worked at all is that it already had
  a native listing route the other surfaces did not.

None of this is a maintenance failure. A list compiled when a release is cut
cannot describe an account that changes after it ships, and the vendors move
faster than the release train. The catalog was structurally incapable of being
right, which is why it was replaced rather than corrected.

## Where the answer comes from instead

The relay is the only component that runs vendor binaries, so it is where
availability is read. Each poll refreshes a per-surface reading on its own
cadence and carries it on the heartbeat the machine already sends. A model an
account gains is visible fleet-wide within about a minute, with no release
involved.

Two facts drove the shape:

**A failure is not a withdrawal.** A probe that times out has learned nothing
about what the account can select. Reporting an empty list would say the
opposite — that the surface offers nothing — so a failed attempt keeps the
models it last saw, keeps their original observation time, and flips the
status to `stale` with the reason. A caller reads the status before the list.

**An unanswered surface is not an unavailable one.** `unknown` means the
surface has never answered and `unsupported` means Yoke declares no listing
adapter for it. Neither is evidence about a model, and a routing rule that
treated either as a negative fact would refuse work that would have run.

## Why every surface gets its own reading, including the ones with no adapter

Shipping a CLI adapter proves nothing about the desktop app or editor
extension from the same vendor. If the desktop surfaces were simply absent
from the record, a reader would have to guess whether that meant "no models"
or "not asked", and the convenient guess is to reuse the CLI's answer — which
is exactly the claim nobody has checked. So all eight known surfaces appear,
and a surface with no adapter carries the reason by name.

That reason names Yoke's own registry — "no native model listing adapter is
declared for this surface" — rather than asserting the vendor cannot list
models. An absent adapter is the only fact the observation establishes.
Adding a route later is one registry entry, and the wording does not have to
be walked back.

## What stayed declared

Model *availability* moved; the CLI *flag grammar* did not. Which effort
tokens a surface's flag parses, how a context window is encoded, what shape a
model token may take — these are properties of the command line Yoke builds,
they are the same on every machine, and they belong in the shared contract.
Reasoning options published *per model* are a different fact and travel with
the reading, because one installed app-server offers `ultra` on its newest
model and not on the one beside it.

## Bounds

One machine publishes 211 tokens, so the record omits every field its vendor
did not publish rather than carrying explicit nulls through a document that
is a third empty. The per-surface bound clears a real listing by a wide
margin, and reaching it is reported in the reading's own reason — a silent
truncation would hide exactly the models this work exists to surface.
