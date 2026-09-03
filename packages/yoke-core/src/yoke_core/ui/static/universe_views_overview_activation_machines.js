// The "Connect a harness" module body, drawn per registered machine. The
// engine answers the module for each machine — which harnesses ran from
// it, when, and its own hook health — so one box's history is never read
// as another's. A machine that registered a relay and ran nothing lists
// as next up on its own row while the machines that did stay ✓.

import { el } from "./universe_view_support.js";
import {
  MACHINE_PENDING_COPY,
  MODULE_COPY,
  machineConnectedLine,
  machineMetaLine,
  machineNameOf,
} from "./universe_views_overview_activation_copy.js";
import { renderHarnessTargets } from "./universe_views_overview_activation_health.js";

// Minimal relative formatter for "connected <x> ago": the app has no shared
// clock helper yet and this copy needs only a coarse honest magnitude.
export function relativeTime(iso) {
  const then = Date.parse(String(iso || ""));
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function projectDirectories(documentNode, module, body) {
  for (const project of module.projects || []) {
    const row = el(documentNode, "p", "activation-project");
    row.appendChild(el(documentNode, "span", "mono", project.slug));
    if (project.workspace) {
      row.appendChild(el(documentNode, "span", null, ` · ${project.workspace} · `));
      row.appendChild(el(
        documentNode, "code", null, `cd ${project.workspace}`,
      ));
    }
    body.appendChild(row);
  }
}

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
  const meta = machineMetaLine(machine.surfaces, relativeTime(machine.last_seen_at));
  if (meta) {
    head.appendChild(el(documentNode, "span", "activation-machine-meta", meta));
  }
  row.appendChild(head);
  if (machine.connected) {
    row.appendChild(el(
      documentNode, "p", "activation-copy",
      machineConnectedLine(
        machine.connected.executor, relativeTime(machine.connected.at),
      ),
    ));
  } else {
    row.appendChild(el(documentNode, "p", "activation-copy", MACHINE_PENDING_COPY));
  }
  renderHarnessTargets(documentNode, machine, row);
  return row;
}

// The module's in-progress copy leads only when no machine is listed yet;
// once machines exist, each row says what it is waiting on.
export function harnessBody(documentNode, module, body) {
  const machines = module.machines || [];
  if (module.state === "in_progress" && !machines.length) {
    body.appendChild(el(
      documentNode, "p", "activation-copy", MODULE_COPY.connect_harness.in_progress,
    ));
    projectDirectories(documentNode, module, body);
    return;
  }
  for (const machine of machines) {
    body.appendChild(machineRow(documentNode, machine));
  }
  if (module.state === "in_progress") {
    projectDirectories(documentNode, module, body);
  }
}
