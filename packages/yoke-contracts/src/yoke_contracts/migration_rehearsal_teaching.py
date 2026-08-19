"""CLI teaching for the bindings governed migration rehearsal needs.

Rehearsal refuses three separate ways -- no local database authority, no
item row in the selected universe, no validation database -- and each
refusal is raised by a different layer. The engine's target resolver cannot
import the CLI and the CLI does not statically import the engine, so the
recipes they both name live here.

Keep the wording project-generic: connection names, universe contents, and
declared bindings differ per install, so the teaching names the commands
that report them rather than any particular machine's answers.
"""

from __future__ import annotations

#: Lists registered connections with transport and prod flag, and prints no
#: credential -- the safe answer to "which connection do I rehearse under?".
CONNECTION_READER = "yoke env list"

#: Where the full preflight lives, named by every refusal that hits one step
#: of it so no message has to restate the other two.
PREFLIGHT_HELP_COMMAND = "yoke migration rehearse --help"

#: Re-enters rehearsal through a claimed Yoke source lane so the patched
#: package tree, rather than the installed main checkout, owns imports.
YOKE_SOURCE_REHEARSAL_RECIPE = (
    "yoke dev run -- yoke --env <name> migration rehearse ITEM"
)

#: Provisions, hydrates, and binds the disposable validation database.
#: In-tree, so it runs through the claimed-lane source runner rather than an
#: ambient interpreter that resolves a different checkout's packages.
PROVISION_RECIPE = (
    "yoke dev run -- python3 -m runtime.api.tools.authority_validation_copy"
)

#: Rendered as the ``yoke migration rehearse`` help epilog.
PREFLIGHT_HELP = f"""\
preflight -- rehearsal needs three bindings, in this order:

1. Authority. Rehearsal executes project-local code against a local
   database, so it is never relayed over HTTPS. `{CONNECTION_READER}` names
   every registered connection with its transport and prod flag, and prints
   no credentials; pick a local-postgres one and rerun as
   `yoke --env <name> migration rehearse ITEM`.

2. Item universe. Rehearsal is item-bound: it reads the item's mutation
   profile and compatibility attestation from the selected connection's
   universe. A local connection whose universe holds no such item cannot
   rehearse it, so select the control plane that owns the item row rather
   than merely any non-HTTPS connection.

3. Validation database. Each module is applied to a separate disposable
   database of the same shape, never to the authority. The model's declared
   `runner.config.connection_env_var` plus `_VALIDATION` names that binding
   (Yoke: YOKE_PG_DSN_VALIDATION); rehearsal reads it from the environment,
   otherwise from the machine-local binding file under ~/.yoke/secrets. In
   the Yoke source repo, provision and hydrate it with:

     {PROVISION_RECIPE}

   That derives a disposable database beside the selected authority, creates
   it when the cluster holds none, replaces its contents with a
   credential-free copy of the authority, and writes the binding file --
   reporting database names, never a DSN. Other projects hydrate their own
   declared binding their own way."""


__all__ = [
    "CONNECTION_READER",
    "PREFLIGHT_HELP",
    "PREFLIGHT_HELP_COMMAND",
    "PROVISION_RECIPE",
    "YOKE_SOURCE_REHEARSAL_RECIPE",
]
