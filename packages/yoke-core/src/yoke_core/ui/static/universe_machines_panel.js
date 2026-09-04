// Machine launch capacity above the Sessions roster: vendor plan windows and
// local lane capacity, composed from the relay's safe public projection. A
// status strip an operator scans before launching, not a report they read —
// so every fact is a value in a column, and the words that would repeat on
// every healthy row are left out.

import { el } from "./universe_view_support.js";
import { preciseAge } from "./universe_time.js";
import {
  METER_PIVOT,
  finiteNumber,
  formatBytes,
  headroomMeterPosition,
  headroomTone,
  laneTone,
  loadTone,
  memoryTone,
  planWindowHeadroom,
  windowLabel,
} from "./universe_machines_meters.js";
import {
  renderSessionControlFailure,
  sessionControlCall,
} from "./universe_session_control_data.js";

const LAUNCHABLE_SURFACES = ["claude-cli", "codex-cli", "cursor-cli"];

const LIGHTS = {
  ok: ["machine-light-ok", "ready"],
  silent: ["machine-light-warn", "relay silent"],
  disabled: ["machine-light-crit", "disabled"],
  absent: ["machine-light-off", "not installed"],
};

const UNREADABLE_RECOVERY =
  " — launches still attempt and fail; re-authenticate the CLI";

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

// The reason a reading is missing, drawn where the meters would be: an empty
// meter says nothing is left, and this says nobody knows.
function limitNote(documentNode, reason) {
  const note = el(documentNode, "p", "machine-limit-note");
  note.appendChild(el(documentNode, "span", "machine-limit-reason", reason));
  note.appendChild(el(documentNode, "span", null, UNREADABLE_RECOVERY));
  return note;
}

function headroomTrack(documentNode, headroom, tone) {
  const track = el(documentNode, "span", "machine-headroom-track");
  track.setAttribute("role", "img");
  if (tone === "unread") {
    track.setAttribute("aria-label", "no reading for this window");
    return track;
  }
  const fill = el(documentNode, "i", "machine-headroom-fill");
  fill.style.width = `${headroomMeterPosition(headroom).toFixed(1)}%`;
  track.appendChild(fill);
  // 100% headroom sits at the same place on every bar, so the tick marking it
  // means one thing wherever it is read.
  const pivot = el(documentNode, "i", "machine-headroom-pivot");
  pivot.style.left = `${METER_PIVOT}%`;
  pivot.title = "100% headroom";
  track.appendChild(pivot);
  track.setAttribute(
    "aria-label",
    tone === "wall"
      ? "at the wall; no headroom before this window resets"
      : `${Math.round(headroom)}% headroom; 100% is the sustainable-use pivot`,
  );
  return track;
}

// Label, headroom bar, headroom, quota left. The bar and the bold number are
// the same fact so they cannot disagree; quota left rides behind as the
// supporting one, because the level alone never says whether a pool can run
// out before it resets.
function planWindowRow(documentNode, window) {
  const headroom = planWindowHeadroom(window);
  const tone = headroomTone(headroom);
  const row = el(documentNode, "div", "machine-limit-row");
  row.setAttribute("data-tone", tone);
  const unread = tone === "unread";
  const name = el(
    documentNode,
    "span",
    "machine-limit-name",
    unread ? "no reading" : windowLabel(window),
  );
  // The column caps its width, so the full name stays reachable on hover.
  name.title = name.textContent;
  row.appendChild(name);
  row.appendChild(headroomTrack(documentNode, headroom, tone));
  const quota = finiteNumber(window.remaining_percent);
  row.appendChild(el(
    documentNode,
    "span",
    "machine-limit-headroom",
    unread ? "—" : (tone === "wall" ? "wall" : `${Math.round(headroom)}%`),
  ));
  row.appendChild(el(
    documentNode,
    "span",
    "machine-limit-quota",
    quota === null ? "—" : `${Math.round(quota)}%`,
  ));
  return row;
}

// The surface header doubles as the column header: the two numeric columns are
// the same width here as in the rows below, so the labels sit over what they
// name without costing a row of their own.
function limitColumns(documentNode) {
  const columns = el(documentNode, "span", "machine-limit-columns");
  columns.appendChild(el(
    documentNode, "span", "machine-limit-headroom", "headroom",
  ));
  columns.appendChild(el(documentNode, "span", "machine-limit-quota", "quota"));
  return columns;
}

function surfaceHead(documentNode, relay, surface, state, reading) {
  const [lightClass, label] = LIGHTS[state];
  const head = el(documentNode, "div", "machine-surface-head");
  const light = el(documentNode, "span", `machine-light ${lightClass}`);
  light.title = label;
  light.setAttribute("role", "img");
  light.setAttribute("aria-label", label);
  head.appendChild(light);
  head.appendChild(el(documentNode, "span", "machine-surface-name", surface));
  if (reading?.plan_tier) head.appendChild(el(
    documentNode, "span", "machine-plan-tier", reading.plan_tier,
  ));
  const version = (relay.surface_versions || {})[surface];
  if (version) head.appendChild(el(
    documentNode, "span", "machine-surface-version", version,
  ));
  if (reading?.windows?.length) head.appendChild(limitColumns(documentNode));
  return head;
}

function surfaceRow(documentNode, relay, surface) {
  const [state, reason] = surfaceState(relay, surface);
  const row = el(
    documentNode, "section", `machine-surface machine-surface-${state}`,
  );
  const reading = (relay.plan_limits || {})[surface];
  row.appendChild(surfaceHead(documentNode, relay, surface, state, reading));
  if (reason) row.appendChild(el(
    documentNode, "p", "machine-surface-reason", reason,
  ));
  if (reading?.windows?.length) {
    const limits = el(documentNode, "div", "machine-limit-list");
    // Ordered by headroom, so the wall this machine hits first is the top row;
    // a window nobody could read sorts last, having named no runway at all.
    const sorted = [...reading.windows].sort((left, right) => {
      const leftValue = planWindowHeadroom(left);
      const rightValue = planWindowHeadroom(right);
      return (leftValue ?? Infinity) - (rightValue ?? Infinity);
    });
    for (const window of sorted) {
      limits.appendChild(planWindowRow(documentNode, window));
      if (window.status !== "ok" && window.reason) {
        limits.appendChild(limitNote(documentNode, window.reason));
      }
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
  const age = preciseAge(relay.last_seen_at);
  head.appendChild(el(
    documentNode,
    "span",
    "machine-meta",
    [live ? relay.state : "silent", age].filter(Boolean).join(" · "),
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
