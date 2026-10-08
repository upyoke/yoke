/** Canonical owned instants. Date is used only for whole-second calendar math. */
const qualified = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?([Zz]|([+-])(\d{2}):(\d{2}))$/;

function invalid(): never {
  throw new Error("invalid_instant: supply a valid RFC3339 timestamp with an explicit UTC offset and at most six fractional digits; use null only where the owner permits absence.");
}

/** Normalize qualified RFC3339 without dropping database microseconds. */
export function formatInstant(value: string): string {
  if (typeof value !== "string") return invalid();
  const match = qualified.exec(value);
  if (!match || match[8] === "-00:00") return invalid();
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  const offsetHour = Number(match[10] || 0);
  const offsetMinute = Number(match[11] || 0);
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > 31 ||
      hour > 23 || minute > 59 || second > 59 || offsetHour > 23 || offsetMinute > 59) return invalid();
  const calendar = new Date(0);
  calendar.setUTCFullYear(year, month - 1, day);
  calendar.setUTCHours(hour, minute, second, 0);
  if (calendar.getUTCFullYear() !== year || calendar.getUTCMonth() !== month - 1 ||
      calendar.getUTCDate() !== day) return invalid();
  const offset = (offsetHour * 60 + offsetMinute) * (match[9] === "-" ? -1 : 1);
  calendar.setTime(calendar.getTime() - offset * 60_000);
  if (calendar.getUTCFullYear() < 1 || calendar.getUTCFullYear() > 9999) return invalid();
  return `${calendar.toISOString().slice(0, 19)}.${(match[7] || "").padEnd(6, "0")}Z`;
}

/** PostgreSQL's qualified text encoding is an adapter, never stored wire form. */
export function formatDatabaseInstant(value: string): string {
  if (typeof value !== "string") return invalid();
  return formatInstant(value.replace(" ", "T").replace(/([+-]\d{2})$/, "$1:00"));
}

/** Preserve exact microseconds for comparisons; convert to Date only for display. */
export function instantMicros(value: string): bigint {
  const canonical = formatInstant(value);
  const wholeSecondMillis = Date.parse(`${canonical.slice(0, 19)}Z`);
  return BigInt(wholeSecondMillis) * 1000n + BigInt(canonical.slice(20, 26));
}

/** A Date producer measured milliseconds; trailing zeros add no precision. */
export function instantFromDate(value: Date): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) return invalid();
  return formatInstant(value.toISOString());
}
