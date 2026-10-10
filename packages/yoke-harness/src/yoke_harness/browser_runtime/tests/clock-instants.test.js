'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const os = require('node:os');
const path = require('node:path');
const { accessibilitySnapshot } = require('../src/snapshot');
const { annotatedScreenshot, plainScreenshot } = require('../src/screenshot');

const BaseDate = Date;
const clock = '2026-10-09T15:00:00.123000Z';
const opaque = '2026-10-09T20:00:00.123456+05:00: opaque text';

test('actual capture producers emit fixed-six measured instants and preserve opaque fields', async () => {
  global.Date = class extends BaseDate {
    constructor(...args) { super(...(args.length ? args : [clock])); }
  };
  const page = {
    ariaSnapshot: async () => '- main "Page"',
    evaluate: async () => [],
    screenshot: async () => {},
    viewportSize: () => ({ width: 800, height: 600 }),
    url: () => opaque,
  };
  try {
    const snapshot = await accessibilitySnapshot(page);
    const outputPath = path.join(os.tmpdir(), `owned-clock-${process.pid}.png`);
    const refs = { '1': opaque };
    const plain = await plainScreenshot(page, { outputPath });
    const annotated = await annotatedScreenshot(page, refs, { outputPath });
    for (const result of [snapshot, plain, annotated]) {
      assert.equal(result.timestamp, clock);
      assert.equal(result.url, opaque);
    }
    assert.equal(annotated.refs, refs);
    assert.equal(plain.imagePath, outputPath);
    assert.deepEqual(snapshot.tree, [{ role: 'main', name: 'Page' }]);
  } finally {
    global.Date = BaseDate;
  }
});
