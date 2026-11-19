'use strict';

const assert = require('node:assert/strict');
const express = require('express');
const { createBrowserManager } = require('../src/browser-manager');
const registerExecRoutes = require('../src/routes/exec-routes');
const { applyColorScheme, observeColorScheme } = require('../src/page-color-scheme');

async function serve() {
  const manager = createBrowserManager({ headless: true });
  await manager.launch();
  const app = express();
  app.use(express.json());
  registerExecRoutes(app, manager);
  app.get(['/fixture', '/next'], (_req, res) => res.send(`<!doctype html>
    <style>body { background: rgb(255,255,255); color: rgb(0,0,0) }
    @media (prefers-color-scheme: dark) { body { background: rgb(0,0,0); color: rgb(255,255,255) } }</style>
    <h1>Media preference fixture</h1><span id="mode"></span>
    <button id="reload" onclick="location.reload()">Reload</button><a id="next" href="/next">Next</a>
    <script>document.querySelector('#mode').textContent =
    matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';</script>`));
  const server = await new Promise(resolve => {
    const started = app.listen(0, '127.0.0.1', () => resolve(started));
  });
  const url = `http://127.0.0.1:${server.address().port}`;
  return { manager, url, close: async () => {
    await manager.closeBrowser();
    await new Promise(resolve => server.close(resolve));
  } };
}

async function main() {
  const fixture = await serve();
  if (process.argv.includes('--serve')) {
    console.log(JSON.stringify({ url: fixture.url }));
    process.on('SIGTERM', async () => { await fixture.close(); process.exit(0); });
    return;
  }
  const { manager, url } = fixture;
  try {
    const viewport = { width: 800, height: 600 };
    const ordinary = await manager.openOwnedPage(viewport);
    const manual = await manager.getPage();
    const baseline = await observeColorScheme(manual);
    const dark = await manager.openOwnedPage(viewport, 'dark-case', 'dark');
    const light = await manager.openOwnedPage(viewport, 'light-case', 'light');
    assert.deepEqual(dark.color_scheme, { requested: 'dark', observed: 'dark' });
    assert.deepEqual(light.color_scheme, { requested: 'light', observed: 'light' });
    for (const opened of [dark, light]) {
      const page = manager.ownedPage(opened.pageId);
      await page.goto(`${url}/fixture`);
      await page.reload();
      await page.goto(`${url}/next`);
      assert.equal((await observeColorScheme(page)).observed, opened.color_scheme.requested);
      const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      assert.equal(background, opened === dark ? 'rgb(0, 0, 0)' : 'rgb(255, 255, 255)');
    }
    assert.deepEqual(await observeColorScheme(manual), baseline);
    assert.equal((await observeColorScheme(manager.ownedPage(ordinary.pageId))).observed,
      ordinary.color_scheme.observed);
    await assert.rejects(manager.openOwnedPage(viewport, dark.pageId, 'light'), /color_scheme_owner_conflict/);
    await assert.rejects(manager.openOwnedPage(viewport, dark.pageId), /color_scheme_owner_conflict/);
    await manager.ownedPage(dark.pageId).emulateMedia({ colorScheme: 'light' });
    await assert.rejects(observeColorScheme(manager.ownedPage(dark.pageId)), /color_scheme_mismatch/);
    const resumed = await manager.openOwnedPage(viewport, dark.pageId, 'dark');
    assert.equal(resumed.opened, false);
    assert.equal(resumed.color_scheme.observed, 'dark');
    await manager.closeOwnedPage(dark.pageId);
    const following = await manager.openOwnedPage(viewport);
    assert.deepEqual(following.color_scheme, ordinary.color_scheme);
    await assert.rejects(manager.openOwnedPage(viewport, undefined, 'sepia'), /case_color_scheme_invalid/);
    await assert.rejects(applyColorScheme({ emulateMedia: async () => { throw Error('broken'); } }, 'dark'),
      /color_scheme_emulation_failed.*repair/);
    await assert.rejects(applyColorScheme({ emulateMedia: async () => {}, evaluate: async () => null }, 'dark'),
      /color_scheme_mismatch/);
    await assert.rejects(applyColorScheme({ emulateMedia: async () => {}, evaluate: async () => { throw Error('gone'); } }, 'dark'),
      /color_scheme_observation_failed.*repair/);
    let reads = 0;
    let waits = 0;
    const settling = {
      emulateMedia: async () => {},
      evaluate: async () => {
        if (++reads <= 2) throw Error('Execution context was destroyed');
        return 'dark';
      },
      waitForLoadState: async (state, options) => {
        assert.equal(state, 'domcontentloaded');
        assert.ok(options.timeout > 0 && options.timeout <= 5000);
        waits++;
      },
    };
    assert.deepEqual(await applyColorScheme(settling, 'dark'),
      { requested: 'dark', observed: 'dark' });
    assert.equal(reads, 3);
    assert.equal(waits, 2);
    // Native navigation destroys a document while its media read is pending.
    // Only this diagnostic read may be repeated; no action is replayed.
    const page = manager.ownedPage(light.pageId);
    const evaluate = page.evaluate.bind(page);
    let navigation;
    let first = true;
    page.evaluate = async (...args) => {
      if (!first) return evaluate(...args);
      first = false;
      const pending = evaluate(() => new Promise(resolve => setTimeout(resolve, 1000)));
      navigation = page.goto(`${url}/fixture`).catch(error => ({ error }));
      return pending;
    };
    const reused = await manager.openOwnedPage(viewport, light.pageId, 'light');
    assert.equal((await navigation).url(), `${url}/fixture`);
    page.evaluate = evaluate;
    assert.equal(reused.opened, false);
    assert.deepEqual(reused.color_scheme, { requested: 'light', observed: 'light' });
    const { executeStep } = require('../src/step-runner');
    const capture = await executeStep(page,
      { action: 'screenshot', target: 'h1', capture: true }, { baseUrl: url });
    assert.equal(capture.success, true);
    assert.ok(capture.artifacts.length);
    // A blocked main thread answers no script. The daemon names the page
    // within the observation deadline instead of holding the request until
    // the client's transport limit.
    await manager.openOwnedPage(viewport, 'busy-case');
    const busy = manager.ownedPage('busy-case');
    await busy.goto(`${url}/fixture`);
    await busy.evaluate(() => { setTimeout(() => { for (;;) {} }, 0); });
    const post = async (route, body) => {
      const started = performance.now();
      const response = await fetch(`${url}${route}`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
      });
      return { status: response.status, body: await response.json(), ms: performance.now() - started };
    };
    const unresponsive = /^page_unresponsive: .*within 5s \(url=http:\/\/127\.0\.0\.1:\d+\/fixture\).*do not replay a submit blindly/;
    const reopened = await post('/api/exec/page', { viewport, pageId: 'busy-case' });
    assert.equal(reopened.status, 400);
    assert.match(reopened.body.error, unresponsive);
    assert.ok(reopened.ms >= 4500 && reopened.ms < 10000, `page refusal took ${reopened.ms}ms`);
    assert.equal(manager.ownedPage('busy-case'), busy, 'the unresponsive page stays open, unsubstituted');
    const stepped = await post('/api/exec/step',
      { step: { action: 'screenshot', capture: true }, baseUrl: url, pageId: 'busy-case' });
    assert.equal(stepped.status, 500);
    assert.match(stepped.body.error, unresponsive);
    assert.ok(stepped.ms < 10000, `step refusal took ${stepped.ms}ms`);
    console.log('PASS: page scheme isolation, navigation/reload, ownership, observation, unresponsive page and failure boundaries');
  } finally {
    await fixture.close();
  }
}

main().catch(err => { console.error(err); process.exit(1); });
