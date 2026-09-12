// How a steering group is colored, what ink reads on that color, and the one
// read those colors are ranked from. One module, because the palette, the
// black/white choice against it, and the roster it ranks are the same
// decision seen from three sides: a color nobody can read text on is not a
// usable group color, and a color ranked from one page's own rows is not a
// group's color at all.

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

// Whether black or white reads on a given group color, by WCAG relative
// luminance against both: a filled label has to stay legible across the
// palette's dark violets and its lighter amber-browns alike, and the two
// extra forms the palette itself produces — a `#rrggbb` entry and the
// generated `hsl()` hue — are the only two this has to parse.
const SRGB_LUMINANCE_WEIGHTS = [0.2126, 0.7152, 0.0722];
// Where the two inks swap. 0.179 is the luminance at which black and white
// contrast equally against a background, so each side of it takes whichever
// ink is genuinely the stronger of the two.
const INK_SWAP_LUMINANCE = 0.179;

function channelLuminance(value) {
  const channel = value / 255;
  return channel <= 0.04045
    ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function hslChannels(hue, saturation, lightness) {
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const sector = ((hue % 360) + 360) % 360 / 60;
  const second = chroma * (1 - Math.abs((sector % 2) - 1));
  const [red, green, blue] = [
    [chroma, second, 0], [second, chroma, 0], [0, chroma, second],
    [0, second, chroma], [second, 0, chroma], [chroma, 0, second],
  ][Math.floor(sector) % 6];
  const base = lightness - chroma / 2;
  return [red, green, blue].map((part) => Math.round((part + base) * 255));
}

function colorChannels(color) {
  const text = String(color || "").trim();
  const hex = /^#([0-9a-f]{6})$/i.exec(text);
  if (hex) {
    return [0, 2, 4].map((at) => parseInt(hex[1].slice(at, at + 2), 16));
  }
  const hsl = /^hsl\(\s*([\d.]+)deg\s+([\d.]+)%\s+([\d.]+)%\s*\)$/i.exec(text);
  if (hsl) {
    return hslChannels(
      Number(hsl[1]), Number(hsl[2]) / 100, Number(hsl[3]) / 100,
    );
  }
  return null;
}

// A color this cannot read is not a reason to render unreadable text: white
// on the palette's own range is the safer of the two defaults.
export function steeringGroupInk(color) {
  const channels = colorChannels(color);
  if (!channels) return "#ffffff";
  const luminance = channels
    .map(channelLuminance)
    .reduce((total, part, index) => total + part * SRGB_LUMINANCE_WEIGHTS[index], 0);
  return luminance > INK_SWAP_LUMINANCE ? "#000000" : "#ffffff";
}

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
