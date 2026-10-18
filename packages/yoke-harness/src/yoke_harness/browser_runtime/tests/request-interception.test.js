'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const { test } = require('node:test');
const { chromium } = require('playwright');
const { executeStep } = require('../src/step-runner');
const { refuseStep } = require('../src/step-schema');

test('interception schema rejects invalid modes and function selectors', () => {
  for (const mode of ['hold', 'reject', 'release', 'status']) {
    refuseStep({ action: 'request_interception', function_id: 'qa.activity.read', mode });
  }
  for (const change of [{ mode: 'abort' }, { mode: {} }, { function_id: '' }, { url_pattern: '*' }]) {
    assert.throws(() => refuseStep({ action: 'request_interception', function_id: 'qa.activity.read', mode: 'hold', ...change }));
  }
});

test('real requests are held, rejected and released only for their page/function/origin', async () => {
  const requests = [];
  const server = http.createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    requests.push(body);
    res.writeHead(200, { 'Content-Type': req.method === 'POST' ? 'application/json' : 'text/html' });
    res.end(req.method === 'POST' ? '{"ok":true}' : '<h1>Cards</h1>');
  });
  await new Promise(resolve => server.listen(0, resolve));
  const baseUrl = `http://127.0.0.1:${server.address().port}`;
  const otherOrigin = baseUrl.replace('127.0.0.1', 'localhost');
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();
    const otherPage = await context.newPage();
    const step = async (function_id, mode) => {
      const result = await executeStep(page, { action: 'request_interception', function_id, mode }, { baseUrl });
      assert.equal(result.success, true, result.error);
      return result.interception;
    };
    await step('qa.activity.read', 'hold');
    await step('deployment_flows.list', 'reject');
    await page.goto(baseUrl);
    await otherPage.goto(baseUrl);
    const post = (p, id, url = baseUrl) => p.evaluate(async ({ id, url }) => {
      try {
        const response = await fetch(`${url}/api/functions/call`, { method: 'POST', body: JSON.stringify({ function: id }) });
        return response.status;
      } catch (_) { return 'rejected'; }
    }, { id, url });
    const held = post(page, 'qa.activity.read');
    // Wait for the actual route, not an assumed sleep proving nothing.
    let heldStatus;
    for (let i = 0; i < 100; i++) {
      heldStatus = await step('qa.activity.read', 'status');
      if (heldStatus.pending === 1) break;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    assert.equal(heldStatus.matched, 1);
    assert.equal(heldStatus.pending, 1);
    assert(!requests.some(body => body.includes('qa.activity.read')));
    assert.equal(await post(page, 'deployment_runs.overview'), 200);
    assert.equal(await post(otherPage, 'qa.activity.read'), 200);
    assert.equal(await post(page, 'deployment_flows.list'), 'rejected');
    assert.equal((await step('deployment_flows.list', 'status')).rejected, 1);
    assert.equal(await page.locator('h1').textContent(), 'Cards');
    const rejected = await step('qa.activity.read', 'reject');
    assert.equal(rejected.rejected, 1);
    assert.equal(rejected.pending, 0);
    assert.equal(await held, 'rejected');
    await step('qa.activity.read', 'hold');
    const next = post(page, 'qa.activity.read');
    for (let i = 0; i < 100; i++) {
      if ((await step('qa.activity.read', 'status')).pending === 1) break;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    const released = await step('qa.activity.read', 'release');
    assert.equal(released.released, 1);
    assert.equal(released.pending, 0);
    assert.equal(await next, 200);
    assert.equal(await post(page, 'qa.activity.read'), 200);
    const missing = await executeStep(page, { action: 'request_interception', function_id: 'qa.activity.read', mode: 'status' }, { baseUrl });
    assert.equal(missing.success, false);
    assert.match(missing.error, /browser_interception_missing/);
    // Same function to another origin must not be intercepted. An unrelated
    // request may still fail CORS; the server receipt proves it was sent.
    const foreign = requests.length;
    await post(page, 'deployment_flows.list', otherOrigin);
    assert(requests.slice(foreign).some(body => body.includes('deployment_flows.list')));
    await step('deployment_flows.list', 'release');
    await step('qa.activity.read', 'hold');
    const closing = post(page, 'qa.activity.read').catch(() => 'closed');
    for (let i = 0; i < 100; i++) {
      if ((await step('qa.activity.read', 'status')).pending === 1) break;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    assert.equal((await step('qa.activity.read', 'status')).pending, 1);
    await page.close();
    await closing;
    const fresh = await context.newPage();
    await fresh.goto(baseUrl);
    assert.equal(await post(fresh, 'qa.activity.read'), 200);
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
