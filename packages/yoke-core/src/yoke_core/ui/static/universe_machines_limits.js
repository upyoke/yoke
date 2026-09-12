/**
 * How one machine's launch surfaces and their plan windows are drawn.
 *
 * A surface row is its readiness light, the harness family it belongs to,
 * and the windows that family's plan publishes — one module, because the
 * head's column labels and the rows they sit over are the same alignment.
 *
 * A window is four aligned facts — its name, a headroom bar, the headroom
 * number, and quota left — and every rule about how they relate lives here
 * rather than beside the panel's loading and failure handling. The bar and
 * the bold number render the same fact so they cannot disagree, and a
 * window nobody could read reuses the one "no reading" presentation rather
 * than inventing a second.
 */

import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";
import {
  METER_PIVOT,
  finiteNumber,
  harnessFamilyIdentity,
  headroomMeterPosition,
  headroomTone,
  planWindowHeadroom,
  readingIsStale,
  sortPlanWindows,
  windowLabel,
} from "./universe_machines_meters.js";

const UNREADABLE_RECOVERY =
  " — launches still attempt and fail; re-authenticate the CLI";

// The reason a reading is missing, drawn where the meters would be: an empty
// meter says nothing is left, and this says nobody knows.
export function limitNote(documentNode, reason) {
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
  attachTooltip(documentNode, pivot, "100% headroom");
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
export function planWindowRow(documentNode, window, stale) {
  // A stale reading's headroom is not recomputed from a possibly long-passed
  // `resets_at` — it reads exactly like a window nobody could read, reusing
  // the same "no reading" presentation rather than a second one.
  const headroom = stale ? null : planWindowHeadroom(window);
  const tone = stale ? "unread" : headroomTone(headroom);
  const row = el(documentNode, "div", "machine-limit-row");
  row.setAttribute("data-tone", tone);
  const unread = tone === "unread";
  const name = el(
    documentNode,
    "span",
    "machine-limit-name",
    unread ? "no reading" : windowLabel(window),
  );
  // Deliberately the browser's own title rather than the shared tooltip: the
  // column caps its width, so this reveals the characters the ellipsis ate
  // and repeats what is already on screen instead of explaining anything.
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
    // A stale reading omits its quota outright rather than presenting a
    // number that may be days old as current; a fresh reading still shows
    // its percent even when headroom itself could not be computed above.
    stale || quota === null ? "—" : `${Math.round(quota)}%`,
  ));
  return row;
}

// The surface header doubles as the column header: the two numeric columns are
// the same width here as in the rows below, so the labels sit over what they
// name without costing a row of their own.
export function limitColumns(documentNode) {
  const columns = el(documentNode, "span", "machine-limit-columns");
  columns.appendChild(el(
    documentNode, "span", "machine-limit-headroom", "headroom",
  ));
  columns.appendChild(el(documentNode, "span", "machine-limit-quota", "quota"));
  return columns;
}

const LIGHTS = {
  ok: ["machine-light-ok", "ready"],
  silent: ["machine-light-warn", "relay silent"],
  disabled: ["machine-light-crit", "disabled"],
  absent: ["machine-light-off", "not installed"],
};


function surfaceState(relay, surface) {
  const mark = (relay.surface_policies || []).find(
    (entry) => entry.surface === surface,
  );
  if (mark) return ["disabled", mark.reason || "disabled by an operator"];
  // Never installed and confirmed removed both read as absent, but neither
  // is inferred from the other: `surface_versions` now keeps naming a
  // surface's last-known version past its cache going stale, so only an
  // active removal (its own field, set by the relay's most recent probe) or
  // a version this machine has truly never reported earns this light.
  const neverSeen = !(relay.surface_versions || {})[surface];
  const removed = (relay.surface_confirmed_absent || []).includes(surface);
  if (neverSeen || removed) {
    return ["absent", "surface_absent — not installed on this machine"];
  }
  if (String(relay.liveness) !== "connected") {
    return ["silent", "the relay has not checked in; a launch cannot reach it"];
  }
  return ["ok", ""];
}

function surfaceHead(documentNode, relay, surface, state, reading, stale) {
  const [lightClass, label] = LIGHTS[state];
  const head = el(documentNode, "div", "machine-surface-head");
  const light = el(documentNode, "span", `machine-light ${lightClass}`);
  attachTooltip(documentNode, light, label);
  light.setAttribute("role", "img");
  light.setAttribute("aria-label", label);
  head.appendChild(light);
  // The family heads the meters, because a plan belongs to the harness an
  // operator recognizes as its provider; `surface` stays the key its reading
  // is stored under and the identity every launch and policy call carries.
  const family = harnessFamilyIdentity(surface);
  head.appendChild(el(documentNode, "span", "machine-surface-name", family));
  // A stale tier is omitted with the quota it came from, rather than shown
  // as a badge the reading can no longer back up.
  if (reading?.plan_tier && !stale) head.appendChild(el(
    documentNode, "span", "machine-plan-tier", reading.plan_tier,
  ));
  // A confirmed removal never shows its last-known version beside the
  // light that says the surface is gone — that string is exactly what
  // would otherwise mask the removal.
  const version = (relay.surface_versions || {})[surface];
  if (version && state !== "absent") head.appendChild(el(
    documentNode, "span", "machine-surface-version", version,
  ));
  if (reading?.windows?.length) head.appendChild(limitColumns(documentNode));
  return head;
}

export function surfaceRow(documentNode, relay, surface) {
  const [state, reason] = surfaceState(relay, surface);
  const row = el(
    documentNode, "section", `machine-surface machine-surface-${state}`,
  );
  const reading = (relay.plan_limits || {})[surface];
  // One freshness verdict for the whole reading, applied consistently to its
  // tier, its headroom, and its quota below — never three separate guesses.
  const stale = reading ? readingIsStale(reading.observed_at) : false;
  row.appendChild(surfaceHead(documentNode, relay, surface, state, reading, stale));
  if (reason) row.appendChild(el(
    documentNode, "p", "machine-surface-reason", reason,
  ));
  if (reading?.windows?.length) {
    const limits = el(documentNode, "div", "machine-limit-list");
    // One fixed order every card shares, so the row a reader looks for is
    // where they last saw it: the main weekly level first, then the rest of
    // the general pool, then each model-specific pool kept together. Ordering
    // by measured headroom instead would move rows around as the readings
    // moved and split a pool's own two windows apart.
    for (const window of sortPlanWindows(reading.windows)) {
      limits.appendChild(planWindowRow(documentNode, window, stale));
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
