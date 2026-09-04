// Machine launch capacity above the Sessions roster: vendor plan windows and
// local lane capacity, composed from the relay's safe public projection.

import { el } from "./universe_view_support.js";
import {
  renderSessionControlFailure,
  sessionControlCall,
} from "./universe_session_control_data.js";

const LAUNCHABLE_SURFACES = ["claude-cli", "codex-cli", "cursor-cli"];
const WINDOW_SECONDS = {
  rolling_5h: 5 * 60 * 60,
  rolling_7d: 7 * 24 * 60 * 60,
  monthly: 30 * 24 * 60 * 60,
};
const METER_PIVOT = 68;
const METER_TOP = 1000;

const LIGHTS = {
  ok: ["machine-light-ok", "ready"],
  silent: ["machine-light-warn", "relay silent"],
  disabled: ["machine-light-crit", "disabled"],
  absent: ["machine-light-off", "not installed"],
};

export function planWindowHeadroom(window, now = Date.now()) {
  if (window?.status !== "ok") return null;
  const seconds = WINDOW_SECONDS[window.window_kind];
  const remaining = Number(window.remaining_percent);
  const reset = new Date(window.resets_at).getTime();
  const untilReset = (reset - now) / 1000;
  if (!seconds || !Number.isFinite(remaining) || !Number.isFinite(reset)) {
    return null;
  }
  if (remaining < 0 || remaining > 100 || untilReset <= 0) return null;
  return (seconds * remaining / 100) / untilReset * 100;
}

export function headroomMeterPosition(headroom) {
  const value = Math.max(0, Number(headroom) || 0);
  if (value <= 100) return value / 100 * METER_PIVOT;
  return METER_PIVOT + (100 - METER_PIVOT) * (
    Math.log10(Math.min(value, METER_TOP) / 100) / Math.log10(METER_TOP / 100)
  );
}

function surfaceState(relay, surface) {
  const mark = (relay.surface_policies || []).find(
    (entry) => entry.surface === surface,
  );
  if (mark) return ["disabled", mark.reason || "disabled by an operator"];
  if (!(relay.surface_versions || {})[surface]) {
    return ["absent", "surface_absent — not installed on this machine"];
  }
  if (String(relay.liveness) !== "connected") {
    return ["silent", "the relay has not checked in; a launch cannot reach it"];
  }
  return ["ok", ""];
}

function planWindowRow(documentNode, window) {
  const headroom = planWindowHeadroom(window);
  const row = el(documentNode, "div", "machine-limit-row");
  const name = [window.scope, window.meter, window.window_kind]
    .filter(Boolean).join(" · ");
  row.appendChild(el(
    documentNode, "span", "machine-limit-name", name || "plan limit",
  ));
  if (headroom === null) {
    row.classList.add("is-unknown");
    row.appendChild(el(
      documentNode,
      "span",
      "machine-limit-value",
      window.reason || "reading unavailable",
    ));
    return row;
  }
  const rounded = Math.round(headroom);
  const quota = Math.round(Number(window.remaining_percent));
  row.setAttribute(
    "data-headroom",
    rounded < 100 ? "low" : (rounded < 150 ? "tight" : "healthy"),
  );
  const track = el(documentNode, "span", "machine-headroom-track");
  const fill = el(documentNode, "i", "machine-headroom-fill");
  fill.style.width = `${headroomMeterPosition(headroom).toFixed(1)}%`;
  track.appendChild(fill);
  track.setAttribute("role", "img");
  track.setAttribute(
    "aria-label",
    `${rounded}% headroom; 100% is the sustainable-use pivot`,
  );
  row.appendChild(track);
  row.appendChild(el(
    documentNode,
    "span",
    "machine-limit-value",
    `${rounded}% headroom · ${quota}% quota left`,
  ));
  return row;
}

function surfaceRow(documentNode, relay, surface) {
  const [state, reason] = surfaceState(relay, surface);
  const [lightClass, label] = LIGHTS[state];
  const row = el(documentNode, "section", `machine-surface machine-surface-${state}`);
  const head = el(documentNode, "div", "machine-surface-head");
  const light = el(documentNode, "span", `machine-light ${lightClass}`);
  light.title = label;
  head.appendChild(light);
  head.appendChild(el(documentNode, "span", "machine-surface-name", surface));
  const version = (relay.surface_versions || {})[surface];
  if (version) head.appendChild(el(
    documentNode, "span", "machine-surface-version", version,
  ));
  const reading = (relay.plan_limits || {})[surface];
  if (reading?.plan_tier) head.appendChild(el(
    documentNode, "span", "machine-plan-tier", reading.plan_tier,
  ));
  head.appendChild(el(documentNode, "span", "machine-surface-state", label));
  row.appendChild(head);
  if (reason) row.appendChild(el(
    documentNode, "p", "machine-surface-reason", reason,
  ));
  if (reading?.windows?.length) {
    const limits = el(documentNode, "div", "machine-limit-list");
    const sorted = [...reading.windows].sort((left, right) => {
      const leftValue = planWindowHeadroom(left);
      const rightValue = planWindowHeadroom(right);
      return (leftValue ?? Infinity) - (rightValue ?? Infinity);
    });
    for (const window of sorted) {
      limits.appendChild(planWindowRow(documentNode, window));
    }
    row.appendChild(limits);
  } else if (state !== "absent") {
    row.appendChild(el(
      documentNode,
      "p",
      "machine-limit-unavailable",
      "Plan-limit windows were not reported by this relay.",
    ));
  }
  return row;
}

function capacityLine(documentNode, capacity) {
  const line = el(documentNode, "div", "machine-capacity");
  line.appendChild(el(
    documentNode, "span", "machine-capacity-label", "Machine capacity",
  ));
  line.appendChild(el(
    documentNode,
    "span",
    "machine-capacity-summary",
    capacity?.summary || "Capacity was not reported by this relay.",
  ));
  if (Number(capacity?.max_worker_lanes) > 0) {
    const track = el(documentNode, "span", "machine-capacity-track");
    const fill = el(documentNode, "i", "machine-capacity-fill");
    const used = Math.min(
      100,
      Number(capacity.live_lanes || 0) / Number(capacity.max_worker_lanes) * 100,
    );
    fill.style.width = `${used.toFixed(1)}%`;
    track.appendChild(fill);
    track.setAttribute(
      "aria-label",
      `${capacity.live_lanes || 0} of ${capacity.max_worker_lanes} lanes in use`,
    );
    line.appendChild(track);
  }
  return line;
}

function machineCard(documentNode, relay) {
  const card = el(documentNode, "article", "machine-card");
  const head = el(documentNode, "div", "machine-head");
  const live = String(relay.liveness) === "connected";
  head.appendChild(el(
    documentNode,
    "span",
    `machine-light ${live ? "machine-light-ok" : "machine-light-warn"}`,
  ));
  head.appendChild(el(
    documentNode, "span", "machine-host", relay.hostname || relay.machine_id,
  ));
  head.appendChild(el(
    documentNode, "span", "machine-meta", live ? relay.state : "silent",
  ));
  card.appendChild(head);
  card.appendChild(capacityLine(documentNode, relay.capacity));
  for (const surface of LAUNCHABLE_SURFACES) {
    card.appendChild(surfaceRow(documentNode, relay, surface));
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
      "No relay is connected, so no session can be launched onto this universe.",
    ));
    host.appendChild(panel);
    return;
  }
  const grid = el(documentNode, "div", "machines-grid");
  for (const relay of relays) grid.appendChild(machineCard(documentNode, relay));
  panel.appendChild(grid);
  host.appendChild(panel);
}

export async function loadMachinesPanel(context, host, options = {}) {
  const documentNode = context.document;
  const run = async () => {
    let relays;
    try {
      const result = await sessionControlCall(
        context, "session_control.relay.list", { limit: 500 },
      );
      relays = result.relays || [];
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
        "The relay roster could not be read, so what can run is unknown.",
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
    host.replaceChildren();
    renderMachinesPanel(context, host, relays, options);
  };
  await run();
}
