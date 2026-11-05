// The "Connect a harness" module body, drawn per registered machine. The
// engine answers the module for each machine — which harnesses ran from
// it, when, and its own hook health — so one box's history is never read
// as another's. A machine that registered a relay and ran nothing lists
// as next up on its own row while the machines that did stay ✓.

import { el } from "./universe_view_support.js";
import {
  MACHINE_PENDING_COPY,
  machineConnectedLine,
  machineMetaLine,
  machineNameOf,
} from "./universe_onboarding_copy.js";
import { renderHarnessTargets } from "./universe_onboarding_health.js";
import { preciseAge } from "./universe_time.js";

function machineRow(documentNode, machine) {
  const row = el(documentNode, "section", "activation-machine");
  row.setAttribute("data-machine", machine.machine_id);
  row.setAttribute("data-state", machine.state);
  const head = el(documentNode, "p", "activation-machine-head");
  head.appendChild(el(
    documentNode, "span", "activation-machine-mark",
    machine.state === "activated" ? "✓" : "○",
  ));
  head.appendChild(el(
    documentNode, "span", "activation-machine-name", machineNameOf(machine),
  ));
  const meta = machineMetaLine(machine.surfaces, preciseAge(machine.last_seen_at));
  if (meta) {
    head.appendChild(el(documentNode, "span", "activation-machine-meta", meta));
  }
  row.appendChild(head);
  if (machine.connected) {
    row.appendChild(el(
      documentNode, "p", "activation-copy",
      machineConnectedLine(
        machine.connected.executor, preciseAge(machine.connected.at),
      ),
    ));
  } else {
    row.appendChild(el(documentNode, "p", "activation-copy", MACHINE_PENDING_COPY));
  }
  renderHarnessTargets(documentNode, machine, row);
  return row;
}

export function harnessBody(documentNode, module, body) {
  for (const machine of module.machines || []) {
    body.appendChild(machineRow(documentNode, machine));
  }
}
