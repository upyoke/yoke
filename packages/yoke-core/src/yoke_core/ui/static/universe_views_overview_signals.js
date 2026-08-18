// The Overview's header chrome: the section roster, board-shaped state and
// momentum masthead, and keyboard-accessible section jump strip. Split beside
// universe_views_overview.js so the composition module stays focused on wiring
// reads to panels; nothing here fetches or fabricates a number.

import { el } from "./universe_view_support.js";

// The prototype turns the board's section headings into a compact map of the
// page. Keep the labels and order beside the renderer so the jump strip cannot
// drift from the summaries it navigates.
export const OVERVIEW_SECTIONS = [
  ["strategy", "❖", "Strategy", "where this universe has been, and where VISION points it"],
  ["frontier", "⚡", "Frontier", "what can run now, and why"],
  ["sessions", "◈", "Sessions", "who is working across the universe"],
  ["delivery", "⬈", "Delivery", "what is shipping, and where it stands"],
  ["events", "≋", "Events", "the pulse · newest first"],
  ["doctor", "♥", "Doctor", "the floor · invariants that hold"],
];

const STATE_SIGNALS = [
  ["active", "🎫", "Active"],
  ["pipeline", "💧", "Pipeline"],
  ["backlog", "🌱", "Backlog"],
  ["blocked", "⛔", "Blocked"],
  ["frozen", "🧊", "Frozen"],
  ["done", "✅", "Done"],
];

const MOMENTUM_SIGNALS = [
  ["activity", "📊", "activity"],
  ["code", "💾", "code"],
  ["issues", "📦", "issues"],
  ["strategy", "🧭", "strategy"],
];

function svgElement(documentNode, tag, className) {
  if (typeof documentNode.createElementNS !== "function") {
    return el(documentNode, tag, className);
  }
  const node = documentNode.createElementNS("http://www.w3.org/2000/svg", tag);
  if (className) node.setAttribute("class", className);
  return node;
}

const BASELINE_Y = 25;
const BAND_HEIGHT = 22;
// The terminal board quantizes into five levels above its baseline, so any
// non-zero day occupies at least the first of those five — a fifth of the
// full height, not a hairline. Hold the line chart to the same floor: these
// series are heavy-tailed (one outlier day many times the median), and a
// purely proportional map leaves an ordinary day a fraction of a pixel off
// the baseline — distinct from zero in the markup, indistinguishable to a
// reader.
const MIN_NONZERO_FRACTION = 1 / 5;

// Mirrors yoke_contracts.board.momentum_series.display_bound, which the
// terminal board scales by. The two runtimes are pinned to the same numbers
// by the shared fixture in momentum_display_bound_fixture.json, because the
// series is assembled on whichever side renders it: the board holds one
// project, while this view sums the projects in scope before drawing.
const DISPLAY_BOUND_PERCENTILE = 0.95;

export function displayBound(values) {
  const ordered = [...values].map(Number).sort((left, right) => left - right);
  const positives = ordered.filter((value) => value > 0);
  if (!positives.length) return 0;
  const rank = DISPLAY_BOUND_PERCENTILE * (ordered.length - 1);
  const lower = Math.floor(rank);
  const upper = Math.min(lower + 1, ordered.length - 1);
  const bound = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower);
  return bound > 0 ? bound : positives[positives.length - 1];
}

function sparklineHeight(value, bound) {
  if (value <= 0) return BASELINE_Y;
  const share = bound > 0 ? Math.min(value / bound, 1) : 1;
  const fraction = Math.max(share, MIN_NONZERO_FRACTION);
  return Math.round(BASELINE_Y - fraction * BAND_HEIGHT);
}

function sparkline(documentNode, values, signal) {
  const svg = svgElement(documentNode, "svg", "overview-sparkline");
  svg.setAttribute("viewBox", "0 0 240 28");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${signal} over time`);
  const baseline = svgElement(documentNode, "line", "overview-sparkline-baseline");
  baseline.setAttribute("x1", "0");
  baseline.setAttribute("x2", "240");
  baseline.setAttribute("y1", "26");
  baseline.setAttribute("y2", "26");
  svg.appendChild(baseline);
  const line = svgElement(documentNode, "polyline", "overview-sparkline-line");
  line.setAttribute("data-series", signal);
  const fullHeight = displayBound(values);
  const denominator = Math.max(1, values.length - 1);
  line.setAttribute(
    "points",
    values.map((value, index) => {
      const x = Math.round(index / denominator * 240);
      return `${x},${sparklineHeight(Number(value) || 0, fullHeight)}`;
    }).join(" "),
  );
  svg.appendChild(line);
  return svg;
}

// The terminal board's state/momentum data becomes a product panel rather than
// six large number tiles. State keeps count + proportional meter; momentum
// keeps a 120-day line per source and a truthful activity streak.
export function signalMasthead(documentNode) {
  const masthead = el(documentNode, "section", "overview-masthead");
  const grid = el(documentNode, "div", "overview-mast-grid");
  const stateColumn = el(documentNode, "div", "overview-state-column");
  stateColumn.appendChild(el(documentNode, "div", "overview-block-title", "STATE"));
  const stateNodes = new Map();
  for (const [key, icon, label] of STATE_SIGNALS) {
    const row = el(documentNode, "div", "overview-state-row");
    row.setAttribute("data-state", key);
    row.appendChild(el(documentNode, "span", "overview-state-icon", icon));
    row.appendChild(el(documentNode, "span", "overview-state-label", label));
    const value = el(documentNode, "strong", "overview-state-value", "—");
    row.appendChild(value);
    const meter = el(documentNode, "span", "overview-state-meter");
    const fill = el(documentNode, "i");
    fill.style.width = "0%";
    meter.appendChild(fill);
    row.appendChild(meter);
    stateNodes.set(key, { value, fill });
    stateColumn.appendChild(row);
  }
  grid.appendChild(stateColumn);

  const momentumColumn = el(documentNode, "div", "overview-momentum-column");
  momentumColumn.appendChild(el(
    documentNode, "div", "overview-block-title", "MOMENTUM",
  ));
  const streak = el(
    documentNode, "div", "overview-streak", "🔥 activity is loading",
  );
  momentumColumn.appendChild(streak);
  const momentumNodes = new Map();
  for (const [key, icon, label] of MOMENTUM_SIGNALS) {
    const series = el(documentNode, "div", "overview-momentum-row");
    series.appendChild(el(
      documentNode,
      "span",
      "overview-momentum-label",
      `${icon} ${label}`,
    ));
    const chart = el(documentNode, "span", "overview-momentum-chart");
    series.appendChild(chart);
    momentumNodes.set(key, { chart });
    momentumColumn.appendChild(series);
  }
  grid.appendChild(momentumColumn);
  masthead.appendChild(grid);
  const sync = el(
    documentNode,
    "div",
    "overview-sync",
    "live engine reads · momentum window is loading",
  );
  masthead.appendChild(sync);

  masthead.setUnavailable = () => {
    streak.textContent = "momentum unavailable";
    sync.textContent = "state and momentum read unavailable";
    for (const { chart } of momentumNodes.values()) {
      chart.replaceChildren();
    }
  };
  masthead.setVitals = ({
    stateCounts = {},
    momentum = [],
    days = 120,
    streakDays = 0,
    lifetimePct = null,
  } = {}) => {
    const stateTotal = STATE_SIGNALS.reduce(
      (total, [key]) => total + (Number(stateCounts[key]) || 0),
      0,
    );
    for (const [key, nodes] of stateNodes) {
      const value = Number(stateCounts[key]) || 0;
      nodes.value.textContent = value.toLocaleString("en-US");
      nodes.fill.style.width = stateTotal && value
        ? `${Math.max(2, Math.round(value / stateTotal * 100))}%`
        : "0%";
    }
    for (const [key, nodes] of momentumNodes) {
      const values = momentum.map((row) => Number(row[key]) || 0);
      nodes.chart.replaceChildren(sparkline(documentNode, values, key));
    }
    const streakCount = Number(streakDays) || 0;
    if (streakCount > 0) {
      const fires = "🔥".repeat(Math.min(streakCount, 14));
      const lifetime = lifetimePct == null
        ? ""
        : ` (${Number(lifetimePct).toFixed(2)}%)`;
      streak.textContent = `${fires} ${streakCount}d streak${lifetime}`;
    } else {
      streak.textContent = "no active streak";
    }
    sync.textContent =
      `live engine reads · state is current · momentum window ` +
      `${Number(days) || 120} days · last sync unavailable`;
  };
  return masthead;
}

// A keyboard-accessible section map that stays available while the long
// Overview scrolls. Buttons scroll within this view; the panel-foot links keep
// owning navigation into the full destination screens.
export function sectionJumps(documentNode, panels) {
  const nav = el(documentNode, "nav", "overview-jumps");
  nav.setAttribute("aria-label", "Overview sections");
  for (const [view, icon, label] of OVERVIEW_SECTIONS) {
    const panel = panels.get(view);
    const button = el(
      documentNode, "button", "overview-jump", `${icon} ${label}`,
    );
    button.type = "button";
    button.setAttribute("aria-controls", `overview-${view}`);
    button.addEventListener("click", () => {
      if (typeof panel.scrollIntoView === "function") {
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
    nav.appendChild(button);
  }
  return nav;
}
