// Durable machine roster: registrations are identity; relays are current telemetry.

import { callFunction, el } from "./universe_view_support.js";
import { renderMachinesPanel } from "./universe_machines_panel.js";
import { fetchEndedUsageRows } from "./universe_machines_usage.js";
import {
  machinesById,
  registeredMachineRelays,
  relaysByMachineId,
} from "./universe_machines_roster.js";
import {
  presentSessionControlFailure,
  sessionControlCall,
} from "./universe_session_control_data.js";

function stat(documentNode, value, label) {
  const node = el(documentNode, "div", "machine-roster-stat");
  node.appendChild(el(documentNode, "strong", null, String(value)));
  node.appendChild(el(documentNode, "span", null, label));
  return node;
}

function retiredTable(documentNode, machines) {
  const details = el(documentNode, "details", "machine-retired-list");
  details.appendChild(el(
    documentNode, "summary", null, `Retired machines (${machines.length})`,
  ));
  const table = el(documentNode, "table", "items");
  const head = el(documentNode, "tr");
  for (const label of ["Machine", "Retired", "History"]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const machine of machines) {
    const row = el(documentNode, "tr");
    const link = el(documentNode, "a", "row-link", machine.name);
    link.href = `#/machines/${encodeURIComponent(machine.machine_id)}`;
    const name = el(documentNode, "td");
    name.appendChild(link);
    row.appendChild(name);
    row.appendChild(el(documentNode, "td", null, machine.retired_at || "—"));
    row.appendChild(el(documentNode, "td", null, "Sessions and launches retained"));
    table.appendChild(row);
  }
  details.appendChild(table);
  return details;
}

export function renderMachinesView(context, main, _scope, chromeArg) {
  const chrome = (chromeArg && typeof chromeArg === "object") ? chromeArg : {};
  const documentNode = context.document;
  const status = el(documentNode, "p", "sessions-action-status");
  const stats = el(documentNode, "section", "machine-roster-stats");
  const roster = el(documentNode, "section", "machines-section");
  const retired = el(documentNode, "section", "machines-section");
  main.replaceChildren(status, stats, roster, retired);
  chrome.setPageHead?.({ title: "Machines" });

  const load = async () => {
    status.textContent = "Loading machines…";
    let machines;
    let relays;
    let usageRows;
    try {
      const [machineCall, relayResult, endedUsageRows] = await Promise.all([
        callFunction(context.client, "machine.list", {}),
        sessionControlCall(context, "session_control.relay.list", { limit: 500 }),
        fetchEndedUsageRows(context),
      ]);
      if (!machineCall.envelope.success) throw machineCall;
      machines = machineCall.envelope.result.machines || [];
      relays = relayResult.relays || [];
      usageRows = endedUsageRows;
    } catch (error) {
      if (!context.isMounted()) return;
      status.textContent = presentSessionControlFailure(
        error, "The machine roster could not be read.",
      );
      return;
    }
    if (!context.isMounted()) return;
    const active = machines.filter((row) => !row.retired_at);
    const historical = machines.filter((row) => row.retired_at);
    const relayById = relaysByMachineId(relays);
    const activeRelays = registeredMachineRelays(machines, relays);
    const online = activeRelays.filter((row) => row.liveness === "connected").length;
    const seen = active.filter((row) => relayById.has(String(row.machine_id))).length;
    stats.replaceChildren(
      stat(documentNode, active.length, "machines"),
      stat(documentNode, online, "online"),
      stat(documentNode, active.length - seen, "not seen"),
    );
    status.textContent = active.length
      ? "Registration history and current relay telemetry are shown together."
      : "No active machines are registered.";
    roster.replaceChildren();
    const machineById = machinesById(machines);
    renderMachinesPanel(context, roster, activeRelays, {
      showHeading: false,
      showManagement: true,
      machineById,
      sessions: () => usageRows,
      onRetire: async (machineId) => {
        if (!documentNode.defaultView.confirm(
          "Retire this machine? Its bearer will be revoked; history stays available.",
        )) return;
        const result = await callFunction(
          context.client, "machine.retire", { machine_id: machineId },
        );
        if (!result.envelope.success) {
          status.textContent = presentSessionControlFailure(
            result, "The machine could not be retired.",
          );
          return;
        }
        await load();
      },
    });
    retired.replaceChildren(retiredTable(documentNode, historical));
  };
  load();
}
