import assert from "node:assert/strict";
import { test } from "node:test";
import { instantWireSql } from "../../packages/yoke-core/src/yoke_core/ui/static/time-sql.js";
import {
  formatInstant, formatDatabaseInstant, instantMicros, instantFromDate,
} from "../../packages/yoke-core/src/yoke_core/ui/static/timestamps.js";

test("qualified offsets preserve identical microsecond bytes", () => {
  for (const input of [
    "2026-10-08T16:30:00.123456Z",
    "2026-10-08T12:30:00.123456-04:00",
    "2026-10-08T22:00:00.123456+05:30",
  ]) assert.equal(formatInstant(input), "2026-10-08T16:30:00.123456Z");
  assert.equal(formatInstant("0001-01-01T00:00:00Z"), "0001-01-01T00:00:00.000000Z");
  assert.equal(formatInstant("2024-02-29T23:59:59.1Z"), "2024-02-29T23:59:59.100000Z");
});

test("database adapter retains microseconds under every session offset", () => {
  for (const input of [
    "2026-10-08 16:30:00.123456+00",
    "2026-10-08 12:30:00.123456-04",
    "2026-10-08 22:00:00.123456+05:30",
  ]) assert.equal(formatDatabaseInstant(input), "2026-10-08T16:30:00.123456Z");
});

test("invalid inputs refuse instead of normalizing an invalid calendar", () => {
  for (const input of [
    "", null, "2026-10-08", "2026-10-08T16:30:00", "2026-02-29T00:00:00Z",
    "2026-10-08 16:30:00Z", "2026-10-08T16:30:60Z", "2026-10-08T16:30:00+24:00",
    "2026-10-08T16:30:00+00:99", "2026-10-08T16:30:00-00:00",
    "2026-10-08T16:30:00.1234567Z", "0000-01-01T00:00:00Z",
  ]) assert.throws(() => formatInstant(input), /invalid_instant.*explicit UTC offset/);
});

test("microsecond ordering remains exact before and after Unix epoch", () => {
  assert.equal(instantMicros("2026-10-08T16:30:00.123457Z") -
    instantMicros("2026-10-08T16:30:00.123456Z"), 1n);
  assert.equal(instantMicros("1969-12-31T23:59:59.999999Z"), -1n);
  assert.equal(instantMicros("1970-01-01T00:00:00Z"), 0n);
});

test("browser Date producers truthfully pad millisecond precision", () => {
  assert.equal(instantFromDate(new Date("2026-10-08T16:30:00.123Z")),
    "2026-10-08T16:30:00.123000Z");
  assert.throws(() => instantFromDate(new Date(NaN)), /invalid_instant/);
});

test("SQL projector preserves the caller expression and transaction clock", () => {
  assert.equal(instantWireSql("now()"),
    `to_char((now()) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`);
  assert.equal(instantWireSql("owned.created_at"),
    `to_char((owned.created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`);
});
