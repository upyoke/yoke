/**
 * How one machine's plan windows are drawn.
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
  headroomMeterPosition,
  headroomTone,
  planWindowHeadroom,
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
