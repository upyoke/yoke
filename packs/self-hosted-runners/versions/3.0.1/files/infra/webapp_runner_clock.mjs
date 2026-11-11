/** Owned lifecycle instants; elapsed seconds remain durations. */
import { formatInstant, instantFromDate, instantMicros } from "./webapp_runner_timestamps.mjs";

export function nowInstant() { return instantFromDate(new Date()); }

export function canonicalInstant(value) {
  try {
    if (formatInstant(value) === value) return value;
  } catch (_) {
    // The owner names the stopped-writer recovery, not a runtime conversion.
  }
  throw new Error("runner_instant_invalid: pause writers and convert snapshotted state to canonical UTC before resuming");
}

export function elapsedSeconds(later, earlier) {
  return Number(instantMicros(later) - instantMicros(earlier)) / 1000000;
}

export function compareInstants(left, right) {
  const delta = instantMicros(left) - instantMicros(right);
  return delta < 0n ? -1 : delta > 0n ? 1 : 0;
}

export function latestInstant(left, right) {
  return compareInstants(left, right) >= 0 ? left : right;
}
