'use strict';

const assert = require('node:assert/strict');
const os = require('node:os');
const path = require('node:path');
const { executeScreenshot } = require('../src/step-actions/capture');

(async () => {
  const original = os.tmpdir;
  const temp = path.resolve('platform-temp');
  os.tmpdir = () => temp;
  try {
    let actual;
    const page = { screenshot: async options => { actual = options.path; } };
    const result = await executeScreenshot(page, { capture: true, label: 'temp' }, {});
    assert.equal(path.dirname(actual), temp);
    assert.deepEqual(result.artifacts, [actual]);
    await executeScreenshot(page, { capture: true }, { outputDir: path.resolve('explicit') });
    assert.equal(path.dirname(actual), path.resolve('explicit'));
    console.log('Screenshot capture respects platform temp and explicit output directories.');
  } finally {
    os.tmpdir = original;
  }
})().catch(error => { console.error(error); process.exit(1); });
