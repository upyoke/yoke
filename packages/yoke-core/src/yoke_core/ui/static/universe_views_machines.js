// Durable machine roster: registrations are identity; relays are current telemetry.

import { callFunction, el } from "./universe_view_support.js";
import { renderMachinesPanel } from "./universe_machines_panel.js";
import { fetchRecentUsageRows } from "./universe_machines_usage.js";
import { appendUsageStats } from "./universe_usage_stats.js";
import {
  machinesById,
  registeredMachineRelays,
  relaysByMachineId,
} from "./universe_machines_roster.js";
import {
  presentSessionControlFailure,
  sessionControlCall,
} from "./universe_session_control_data.js";

// The roster's own headline facts, in the one compact shape every summary
// figure on every page uses: the value and what it counts, inline, at the
// height the text needs.
function rosterStats(documentNode, host, facts) {
  host.replaceChildren();
  appendUsageStats(documentNode, host, {
    className: "machine-roster-stats usage-stats",
    stats: facts.map(([value, unit]) => ({ value: String(value), unit })),
  });
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
  status.hidden = true;
  const stats = el(documentNode, "section", "machine-roster-stats-host");
  const roster = el(documentNode, "section", "machines-section");
  const retired = el(documentNode, "section", "machines-section");
  main.replaceChildren(status, stats, roster, retired);
  chrome.setPageHead?.({ title: "Machines" });

  const showStatus = (text, retry) => {
    status.hidden = false;
    status.replaceChildren();
    if (text) status.appendChild(el(documentNode, "span", null, text));
    if (!retry) return;
    const button = el(documentNode, "button", "machines-retry", "Try again");
    button.type = "button";
    button.addEventListener("click", retry);
    status.appendChild(button);
  };

  const load = async () => {
    showStatus("Loading machines…");
    let machines;
    let relays;
    let usageRows;
    try {
      // Cards need machine.list, relay.list, and the 24h usage cohort.
      // sessions.list {open:true} is the slow live roster (bounded at 500)
      // and only feeds machine_id / liveness / holdings onto the cards.
      const [machineCall, relayResult, recentUsageRows] = await Promise.all([
        callFunction(context.client, "machine.list", {}),
        sessionControlCall(context, "session_control.relay.list", { limit: 500 }),
        fetchRecentUsageRows(context),
      ]);
      if (!machineCall.envelope.success) throw machineCall;
      machines = machineCall.envelope.result.machines || [];
      relays = relayResult.relays || [];
      usageRows = recentUsageRows;
    } catch (error) {
      if (!context.isMounted()) return;
      showStatus(presentSessionControlFailure(
        error, "The machine roster could not be read.",
      ));
      return;
    }
    if (!context.isMounted()) return;
    const active = machines.filter((row) => !row.retired_at);
    const historical = machines.filter((row) => row.retired_at);
    const relayById = relaysByMachineId(relays);
    const activeRelays = registeredMachineRelays(machines, relays);
    const online = activeRelays.filter((row) => row.liveness === "connected").length;
    const seen = active.filter((row) => relayById.has(String(row.machine_id))).length;
    rosterStats(documentNode, stats, [
      [active.length, "machines"],
      [online, "online"],
      [active.length - seen, "not seen"],
    ]);
    const machineById = machinesById(machines);
    const paintWork = (openSessions) => {
      roster.replaceChildren();
      renderMachinesPanel(context, roster, activeRelays, {
        showHeading: false,
        showManagement: true,
        machineById,
        sessions: () => usageRows,
        openSessions,
        projectRows: context.projects(),
        onRetire: async (machineId) => {
          if (!documentNode.defaultView.confirm(
            "Retire this machine? Its bearer will be revoked; history stays available.",
          )) return;
          const result = await callFunction(
            context.client, "machine.retire", { machine_id: machineId },
          );
          if (!result.envelope.success) {
            showStatus(presentSessionControlFailure(
              result, "The machine could not be retired.",
            ));
            return;
          }
          await load();
        },
      });
    };
    const showReadyStatus = () => {
      if (active.length) {
        status.hidden = true;
        status.replaceChildren();
        return;
      }
      showStatus("No active machines are registered.");
    };
    showReadyStatus();
    paintWork({ status: "loading" });
    retired.replaceChildren(retiredTable(documentNode, historical));
    const loadOpenRoster = async () => {
      paintWork({ status: "loading" });
      try {
        const openRoster = await callFunction(
          context.client, "sessions.list", { open: true },
        );
        if (!context.isMounted()) return;
        if (!openRoster.envelope.success) throw openRoster;
        paintWork(openRoster.envelope.result?.rows || []);
        showReadyStatus();
      } catch (error) {
        if (!context.isMounted()) return;
        const message = presentSessionControlFailure(
          error, "Open sessions could not be read.",
        );
        paintWork({ status: "error", message });
        showStatus(message, loadOpenRoster);
      }
    };
    await loadOpenRoster();
  };
  load();
}
