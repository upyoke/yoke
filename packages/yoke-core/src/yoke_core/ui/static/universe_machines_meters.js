// How a machine's meters read: the scale a headroom bar is drawn on, the
// short window label that stands in for the vendor's meter id, and the
// pressure tone every value carries. One module, because a colour is a
// threshold and a threshold stated twice is a threshold that disagrees.

const WINDOW_SECONDS = {
  rolling_5h: 5 * 60 * 60,
  rolling_7d: 7 * 24 * 60 * 60,
  monthly: 30 * 24 * 60 * 60,
};

// 100% headroom is not a midpoint, it is the point: exactly enough runway to
// reach the reset. It sits at the same place on every bar so the tick marking
// it means one thing, and everything below it — the only range where anything
// is at stake — takes most of the width. Above it the scale is logarithmic,
// because the gap between 800% and 900% of runway nobody will use is not worth
// the pixels the gap between 90% and 100% needs.
export const METER_PIVOT = 68;
const METER_TOP = 1000;

// Short human window names. A vendor meter id identifies a bucket to the
// vendor's API; it does not name a window to an operator, so it never reaches
// the card.
const WINDOW_LABELS = {
  rolling_5h: "rolling 5h",
  rolling_7d: "weekly",
  monthly: "monthly",
};

// Free memory against the machine's own total, load against its own cores, and
// lanes against the cap its relay published: each fact is read as a fraction of
// what this machine has, so one threshold covers a laptop and a studio.
const MEMORY_CRIT_FRACTION = 0.1;
const MEMORY_WARN_FRACTION = 0.25;
const LOAD_CRIT_PER_CORE = 1;
const LOAD_WARN_PER_CORE = 0.75;
const LANE_WARN_FRACTION = 0.75;

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"];

// `Number(null)` is 0, so a fact the relay never published would otherwise read
// as a machine with no memory left and a pool at the wall. Absent stays absent.
export function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

// Matches the engine's own `format_bytes` ladder, so "2.1 GB free" on the card
// reads the same as the capacity summary the control plane composes.
export function formatBytes(value) {
  const bytes = finiteNumber(value);
  if (bytes === null) return "unknown";
  let size = Math.max(0, bytes);
  let index = 0;
  while (size >= 1024 && index < BYTE_UNITS.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index < 3 ? 0 : 1)} ${BYTE_UNITS[index]}`;
}

// Remaining runway ÷ time to reset. Under 100% is the only value that can hit
// a wall before it resets, which is why the bar measures this and not the
// quota left beside it.
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

// `rolling 5h · all`, `weekly · Fable`. A window whose kind the vendor has not
// taught us yet still names what it covers rather than falling back to the id.
export function windowLabel(window) {
  const kind = WINDOW_LABELS[window?.window_kind];
  const scope = String(window?.scope || "").trim();
  if (!kind) return scope || "plan limit";
  return scope ? `${kind} · ${scope}` : kind;
}

// A pool with no runway left is at the wall, which is a different fact from a
// pool nobody could read; both are different from one merely running warm.
export function headroomTone(headroom) {
  if (headroom === null || headroom === undefined) return "unread";
  if (Math.round(headroom) <= 0) return "wall";
  return headroom < 100 ? "warn" : "ok";
}

export function memoryTone(freeBytes, totalBytes) {
  const free = finiteNumber(freeBytes);
  const total = finiteNumber(totalBytes);
  if (free === null || total === null || total <= 0) return "unknown";
  const fraction = free / total;
  if (fraction < MEMORY_CRIT_FRACTION) return "crit";
  return fraction < MEMORY_WARN_FRACTION ? "warn" : "ok";
}

export function loadTone(loadAverage, cores) {
  const load = finiteNumber(loadAverage);
  const cpus = finiteNumber(cores);
  if (load === null || cpus === null || cpus <= 0) return "unknown";
  const perCore = load / cpus;
  if (perCore >= LOAD_CRIT_PER_CORE) return "crit";
  return perCore >= LOAD_WARN_PER_CORE ? "warn" : "ok";
}

export function laneTone(liveLanes, maxLanes) {
  const live = finiteNumber(liveLanes) ?? 0;
  const cap = finiteNumber(maxLanes);
  if (cap === null || cap <= 0) return "unknown";
  if (live >= cap) return "crit";
  return live / cap >= LANE_WARN_FRACTION ? "warn" : "ok";
}
