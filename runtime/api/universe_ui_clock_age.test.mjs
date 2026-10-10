import assert from "node:assert/strict";
import test from "node:test";
import {
  relativeAge, relativeAgePhrase, preciseAge, isInstantRelativeTime, relativeTime,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_time.js";
import { formatInstant } from "../../packages/yoke-core/src/yoke_core/ui/static/timestamps.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

for (const [threshold, relativeBefore, relativeAt, preciseBefore, preciseAt] of [
  [1, "now", "now", "0s", "1s"],
  [60, "now", "1m", "59s", "1m"],
  [3600, "59m", "1h", "59m", "1h"],
  [86400, "23h", "24h", "23h", "1d"],
  [172800, "47h", "2d", "1d", "2d"],
]) {
  test(`relative display preserves microseconds at the ${threshold}-second boundary`, () => {
    const now = Date.parse("1970-01-04T00:00:00Z");
    const exact = formatInstant(new Date(now - threshold * 1000).toISOString());
    const younger = exact.replace(".000000Z", ".000001Z");
    assert.equal(relativeAge(younger, now), relativeBefore);
    assert.equal(relativeAge(exact, now), relativeAt);
    assert.equal(preciseAge(younger, now), preciseBefore);
    assert.equal(preciseAge(exact, now), preciseAt);
  });
}

for (const value of [
  "1969-12-31T23:59:00.000001Z",
  "1969-12-31T18:59:00.000001-05:00",
  "1970-01-01T05:44:00.000001+05:45",
]) {
  test(`qualified pre-epoch clock ${value} keeps exact relative age and HTML wire`, () => {
    assert.equal(relativeAge(value, 0), "now");
    assert.equal(relativeAgePhrase(value, 0), "now");
    assert.equal(preciseAge(value, 0), "59s");
    assert.equal(isInstantRelativeTime(value, 0), true);
    const time = relativeTime(new FakeDocument(), value, 0);
    assert.equal(time.textContent, "now");
    assert.equal(time.attributes.get("datetime"), "1969-12-31T23:59:00.000001Z");
    // HTML's millisecond display metadata remains its declared protocol value.
    assert.equal(time.attributes.get("data-ms"), "-60000");
  });
}

test("opaque and ambiguous clock fallbacks never establish freshness", () => {
  for (const value of [
    null, "now", "not a timestamp", "1969-12-31", "1969-12-31T23:59:00",
    "1969-12-31T23:59:00-00:00", "2026-02-29T00:00:00Z",
  ]) {
    assert.equal(preciseAge(value, 0), null);
    assert.equal(isInstantRelativeTime(value, 0), false);
  }
  assert.equal(relativeAge("now", 0), "now");
  assert.equal(relativeAge("not a timestamp", 0), "not a timestamp");
  assert.equal(relativeAge(null, 0), "recently");
});

test("known future clocks clamp at zero; invalid millisecond reference has no freshness", () => {
  const future = "1970-01-01T00:00:00.000001Z";
  assert.equal(relativeAge(future, 0), "now");
  assert.equal(preciseAge(future, 0), "0s");
  assert.equal(isInstantRelativeTime(future, 0), true);
  for (const now of [Number.NaN, Number.POSITIVE_INFINITY, 0.000001]) {
    assert.equal(preciseAge(future, now), null);
    assert.equal(isInstantRelativeTime(future, now), false);
  }
});
