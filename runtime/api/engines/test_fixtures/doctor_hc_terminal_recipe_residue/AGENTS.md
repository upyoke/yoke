# Regression fixture for HC-terminal-recipe-residue

This is a deliberately-stale guidance surface used by
``test_doctor_hc_terminal_recipe_residue.py`` to assert that the HC fails
closed on retired terminal-soup recipes.

Do NOT teach the patterns below in real guidance. They appear here only
because the HC test injects this fixture into a temporary scan root and
verifies it FAILs.

## Banned-literal residue

The following lines reproduce historical terminal-soup recipes whose
function-call replacements are listed in
``runtime/api/service_client_structured_api_adapter_inventory.py``:

* Capability probe via shell choreography (covered by
  ``projects.capability.has``):

      python3 -m yoke_core.cli.db_router projects has-capability yoke ephemeral-env 2>&1
      python3 -m yoke_core.cli.db_router projects has-capability yoke ephemeral-env; echo $?

* Raw SQL against the control plane (covered by typed reads):

      sqlite3 data/yoke.db "SELECT 1"

## Registry-aware function-covered recipe

The following mutating Yoke CLI adapter is wrapped with shell
choreography ($(...) capture), so the HC's registry-aware second pass
should flag it even though the literal text is not in the banned-list:

      _write_result=$(python3 -m yoke_core.cli.db_router items update YOK-N spec refreshed)
