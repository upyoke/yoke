// Machine launch capacity above the Sessions roster: vendor plan windows and
// local lane capacity, composed from the relay's safe public projection. A
// status strip an operator scans before launching, not a report they read —
// so every fact is a value in a column, and the words that would repeat on
// every healthy row are left out.

import { attachTooltip } from "./universe_tooltip.js";
import { callFunction, el } from "./universe_view_support.js";
import { preciseAge } from "./universe_time.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import {
  finiteNumber,
  formatBytes,
  laneTone,
  loadTone,
  memoryTone,
} from "./universe_machines_meters.js";
import { surfaceRow } from "./universe_machines_limits.js";
import { appendMachineUsage, fetchRecentUsageRows } from "./universe_machines_usage.js";
import { machinesById, registeredMachineRelays } from "./universe_machines_roster.js";
import {
  renderSessionControlFailure,
  sessionControlCall,
} from "./universe_session_control_data.js";

export const LAUNCHABLE_SURFACES = ["claude-cli", "codex-cli", "cursor-cli"];

function capacityFact(documentNode, text, tone) {
  const fact = el(documentNode, "span", "machine-capacity-fact", text);
  fact.setAttribute("data-tone", tone);
  return fact;
}

// Capacity, which is the same question from the other side: a machine can hold
// quota and still have no room to run. Free memory and load carry no ceiling
// the machine publishes, so lanes against the declared cap is the only one
// that gets a bar.
function capacityLine(documentNode, capacity) {
  const line = el(documentNode, "div", "machine-capacity");
  line.appendChild(el(
    documentNode, "span", "machine-capacity-label", "machine",
  ));
  const cap = finiteNumber(capacity?.max_worker_lanes);
  const lanes = finiteNumber(capacity?.live_lanes) ?? 0;
  const lanePressure = laneTone(lanes, cap);
  line.appendChild(capacityFact(
    documentNode,
    `${formatBytes(capacity?.free_memory_bytes)} free`,
    memoryTone(capacity?.free_memory_bytes, capacity?.total_memory_bytes),
  ));
  const load = finiteNumber(capacity?.load_average_1m);
  line.appendChild(capacityFact(
    documentNode,
    `load ${load === null ? "unknown" : load.toFixed(1)}`,
    loadTone(capacity?.load_average_1m, capacity?.core_count),
  ));
  line.appendChild(capacityFact(
    documentNode,
    `lanes ${lanes}/${cap !== null && cap > 0 ? cap : "?"}`,
    lanePressure,
  ));
  if (cap !== null && cap > 0) {
    const track = el(documentNode, "span", "machine-capacity-track");
    const fill = el(documentNode, "i", "machine-capacity-fill");
    fill.style.width = `${Math.min(100, lanes / cap * 100).toFixed(1)}%`;
    track.appendChild(fill);
    track.setAttribute("data-tone", lanePressure);
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", `${lanes} of ${cap} lanes in use`);
    line.appendChild(track);
  } else if (capacity?.summary) {
    // A relay that publishes no cap is an older relay, not a roomy machine.
    line.appendChild(el(
      documentNode, "span", "machine-capacity-unreported", capacity.summary,
    ));
  }
  return line;
}

// Whose machine this is belongs beside its name, not at the far end of the
// card: the two names are one identity, and an operator scanning a grid reads
// them together. They shrink independently, so two long names each keep their
// opening characters instead of one spending the room the other needed, and
// neither reaches the status that has to stay legible at the end of the row.
function machineHead(documentNode, relay, options) {
  const head = el(documentNode, "div", "machine-head");
  // The names travel together so the status is the only thing a narrow card
  // can step down to a second line: a group that holds its own line keeps
  // both names truncating on one instead of each claiming a line of its own.
  const names = el(documentNode, "div", "machine-names");
  const live = String(relay.liveness) === "connected";
  names.appendChild(el(
    documentNode,
    "span",
    `machine-light ${live ? "machine-light-ok" : "machine-light-warn"}`,
  ));
  const name = options.name || relay.hostname || relay.machine_id;
  const host = el(documentNode, "span", "machine-host", name);
  // A truncated name still answers in full on hover, tap and focus, through
  // the one explanation surface the product already draws everywhere else.
  attachTooltip(documentNode, host, name);
  names.appendChild(host);
  const ownerName = options.owner || relay.owner || "";
  if (ownerName) {
    const owner = el(documentNode, "span", "machine-owner");
    owner.appendChild(el(
      documentNode, "span", "machine-owner-name", ownerName,
    ));
    attachTooltip(documentNode, owner, ownerName);
    names.appendChild(owner);
  }
  head.appendChild(names);
  const age = preciseAge(relay.last_seen_at);
  head.appendChild(el(
    documentNode,
    "span",
    "machine-meta",
    [live ? relay.state : "silent", age].filter(Boolean).join(" · "),
  ));
  return head;
}

// Details and Retire act on the machine registry, so they ride only the page
// that owns that registry. Every other page embeds this card as a status tile
// and asks for no management bar, which is why the caller says so explicitly
// rather than the card guessing from the route it happens to be rendered on.
function managementBar(documentNode, relay, options) {
  const footer = el(documentNode, "div", "machine-card-footer");
  const detail = el(
    documentNode, "a", "item-button machine-detail-link", "Details",
  );
  detail.href = options.detailHref || buildUniverseRoute(
    "machines", null, relay.machine_id,
  );
  footer.appendChild(detail);
  if (typeof options.onRetire === "function") {
    const retire = el(
      documentNode, "button", "item-button machine-retire", "Retire",
    );
    retire.type = "button";
    retire.addEventListener("click", () => options.onRetire(relay.machine_id));
    footer.appendChild(retire);
  }
  return footer;
}

export function machineCard(documentNode, relay, sessions, options = {}) {
  const card = el(documentNode, "article", "machine-card");
  card.setAttribute("data-machine-id", String(relay.machine_id || ""));
  card.appendChild(machineHead(documentNode, relay, options));
  card.appendChild(capacityLine(documentNode, relay.capacity));
  appendMachineUsage(documentNode, card, relay, sessions);
  for (const surface of LAUNCHABLE_SURFACES) {
    card.appendChild(surfaceRow(documentNode, relay, surface));
  }
  if (options.showManagement) {
    card.appendChild(managementBar(documentNode, relay, options));
  }
  return card;
}

export function renderMachinesPanel(context, host, relays, options = {}) {
  const documentNode = context.document;
  const panel = el(documentNode, "section", "machines-panel");
  if (options.showHeading !== false) panel.appendChild(el(
    documentNode, "h2", "machines-panel-head", "Machines",
  ));
  if (!relays.length) {
    panel.appendChild(el(
      documentNode,
      "p",
      "machines-empty",
      "No machine is registered, so no session can be launched onto this universe.",
    ));
    host.appendChild(panel);
    return;
  }
  const grid = el(documentNode, "div", "machines-grid");
  // The sessions accessor is read at render time so a redraw picks up
  // whatever 24h-usage rows were last fetched rather than whatever it
  // held when first mounted.
  const sessions = typeof options.sessions === "function" ? options.sessions() : [];
  for (const relay of relays) {
    const machine = options.machineById?.get?.(String(relay.machine_id)) || {};
    grid.appendChild(machineCard(documentNode, relay, sessions, {
      name: machine.name,
      owner: machine.owner,
      onRetire: options.onRetire,
      showManagement: options.showManagement,
    }));
  }
  panel.appendChild(grid);
  host.appendChild(panel);
}

export async function loadMachinesPanel(context, host, options = {}) {
  const documentNode = context.document;
  let fetched = null;
  const run = async () => {
    let relays;
    let machineById;
    let usageRows;
    try {
      const [machineCall, relayResult, recentUsageRows] = await Promise.all([
        callFunction(context.client, "machine.list", {}),
        sessionControlCall(context, "session_control.relay.list", { limit: 500 }),
        fetchRecentUsageRows(context, options.projects || []),
      ]);
      if (!machineCall.envelope.success) throw machineCall;
      const machines = machineCall.envelope.result.machines || [];
      relays = registeredMachineRelays(machines, relayResult.relays || []);
      machineById = machinesById(machines);
      usageRows = recentUsageRows;
    } catch (error) {
      if (!context.isMounted()) return;
      host.replaceChildren();
      const panel = el(documentNode, "section", "machines-panel");
      if (options.showHeading !== false) panel.appendChild(el(
        documentNode, "h2", "machines-panel-head", "Machines",
      ));
      const failure = el(documentNode, "div", "machines-failure");
      renderSessionControlFailure(
        failure,
        error,
        "The machine roster could not be read, so what can run is unknown.",
      );
      const retry = el(documentNode, "button", "machines-retry", "Try again");
      retry.type = "button";
      retry.addEventListener("click", run);
      failure.appendChild(retry);
      panel.appendChild(failure);
      host.appendChild(panel);
      return;
    }
    if (!context.isMounted()) return;
    fetched = { relays, machineById, usageRows };
    host.replaceChildren();
    renderMachinesPanel(context, host, relays, {
      ...options, machineById, sessions: () => usageRows,
    });
  };
  await run();
  // Redrawing reuses the relays and usage rows already fetched: the
  // roster re-renders on every filter change, and the machine tiles that
  // sum 24h usage must follow without asking the control plane again.
  return {
    redraw: () => {
      if (!fetched || !context.isMounted()) return;
      host.replaceChildren();
      renderMachinesPanel(context, host, fetched.relays, {
        ...options,
        machineById: fetched.machineById,
        sessions: () => fetched.usageRows,
      });
    },
  };
}
