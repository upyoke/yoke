'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const { test } = require('node:test');
const { chromium } = require('playwright');
const { executeStep } = require('../src/step-runner');

test('click dialogs are answered once and leave evidence and no listener', async () => {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(`<!doctype html><title>Dialog fixture</title><main>
      <button id="confirm" onclick="document.querySelector('output').textContent = confirm('Remove installation?')">Confirm</button>
      <button id="twice" onclick="confirm('First'); confirm('Second')">Twice</button>
      <button id="plain">Plain</button><output></output></main>`);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const baseUrl = `http://127.0.0.1:${server.address().port}`;
    await page.goto(baseUrl);
    const click = (target, dialog) => executeStep(page, {
      action: 'click', target, ...(dialog === undefined ? {} : { dialog }),
    }, { baseUrl });

    for (const accept of [true, false]) {
      const result = await click('#confirm', accept ? 'accept' : 'dismiss');
      assert.equal(result.success, true, result.error);
      assert.equal(await page.locator('output').textContent(), String(accept));
      assert.deepEqual(result.dialogs, [{
        type: 'confirm', message: 'Remove installation?', accepted: accept,
      }]);
      assert.equal(page.listenerCount('dialog'), 0);
    }

    const twice = await click('#twice', 'accept');
    assert.equal(twice.success, false);
    assert.match(twice.error, /^browser_dialog_unanswered:.*Second/);
    assert.deepEqual(twice.dialogs.map((item) => item.accepted), [true, false]);

    const missing = await click('#plain', 'accept');
    assert.equal(missing.success, false);
    assert.match(missing.error, /^browser_dialog_missing:/);

    const unanswered = await click('#confirm');
    assert.equal(unanswered.success, false);
    assert.match(unanswered.error, /^browser_dialog_unanswered: confirm "Remove installation\?"/);
    assert.match(unanswered.error, /Declare dialog/);
    assert.equal(unanswered.dialogs[0].accepted, false);
    assert.equal(page.listenerCount('dialog'), 0, 'failed steps remove their listener');

    for (const invalid of [null, true, {}, { accept: true }, 'yes']) {
      const refused = await click('#confirm', invalid);
      assert.equal(refused.success, false);
      assert.match(refused.error, /dialog requires "accept" or "dismiss"/);
      assert.equal(page.listenerCount('dialog'), 0);
    }

    const next = await click('#plain');
    assert.equal(next.success, true, next.error);
    assert.equal(next.dialogs, undefined);
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
});
