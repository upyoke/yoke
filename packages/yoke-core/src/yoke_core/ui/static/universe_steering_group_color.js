// How steering-group colors are assigned and the one roster those colors are
// ranked from.

import { callFunction } from "./universe_view_support.js";

// A steering group's color is a fact about the group, not the theme — like
// the harness brand marks in theme.css, it does not vary between light and
// dark. Six hues, chosen for pairwise distinctness and to stay clear of the
// existing state hues (good/warn/crit/run/park).
const STEERING_GROUP_PALETTE = [
  "#7c3aed", // violet
  "#0d9488", // teal
  "#db2777", // rose
  "#0e7490", // cyan
  "#a16207", // amber-brown
  "#4338ca", // indigo
];

// Rotating by the golden angle spreads consecutive extra hues well clear of
// their immediate neighbor — not a claim that no two of them, out of an
// unbounded run, can ever land close together.
const GOLDEN_ANGLE_DEGREES = 137.508;

function paletteColorAt(rank) {
  if (rank < STEERING_GROUP_PALETTE.length) return STEERING_GROUP_PALETTE[rank];
  const hue = ((rank - STEERING_GROUP_PALETTE.length) * GOLDEN_ANGLE_DEGREES) % 360;
  return `hsl(${hue.toFixed(1)}deg 65% 38%)`;
}

// Ranked by sorted id, not by position in any one page's own fetch: Overview,
// Sessions, and the detail view each fetch their own rows (Sessions scopes to
// one project, Overview does not), so ranking by position within a single
// call's rows gave the same group different colors on different pages. The
// fix is feeding this one function the same complete, app-wide roster on
// every call (mountUniverseApp fetches it once, like context.projects()) —
// a page-local subset never reaches this function at all.
export function computeSteeringGroupColors(rows) {
  const distinctIds = [...new Set(
    (Array.isArray(rows) ? rows : [])
      .map((row) => row?.steering_group_session_id)
      .filter((id) => id !== undefined && id !== null && id !== "")
      .map((id) => String(id)),
  )].sort();
  const colors = new Map();
  distinctIds.forEach((id, rank) => colors.set(id, paletteColorAt(rank)));
  return colors;
}

// The roster the colors are ranked from, held where the ranking lives. The
// read is decoration — it tints cards — so it must never gate a screen's
// first paint; `refresh()` is fire-and-forget and a failure leaves the last
// ranking standing. Overview and Sessions call it again to catch a group
// that started mid-session.
export function createSteeringGroupColors(client, isMounted) {
  let colors = new Map();
  return {
    colors: () => colors,
    // For a screen that already holds the same open roster. It is the very
    // rows `refresh()` would go and read, so asking for them again is one
    // more copy of the slowest read on the page for an answer already in
    // hand.
    adopt: (rows) => {
      if (!isMounted()) return;
      colors = computeSteeringGroupColors(rows);
    },
    refresh: () => Promise.resolve().then(() => callFunction(
      client, "sessions.list", { per_project: true, open: true },
    )).then((callResult) => {
      if (!isMounted()) return;
      const envelope = callResult.envelope;
      colors = computeSteeringGroupColors(
        (envelope?.success && envelope.result?.rows) || [],
      );
    }).catch(() => {}),
  };
}
