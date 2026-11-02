'use strict';

/**
 * Tests for how a navigate step reads the HTTP status it landed on.
 *
 * Run: node tests/step-runner-navigate-status.test.js
 *
 * Covers: an authentication refusal (401) and a missing page (404) each fail
 * the navigate step by name instead of letting later steps run against a
 * page the case did not ask for. Other responses expose their HTTP status.
 */

const http = require('http');
const { chromium } = require('playwright');
const { executeStep } = require('../src/step-runner');

let testCount = 0;
let passCount = 0;
let failCount = 0;

function assert(condition, message) {
  testCount++;
  if (condition) {
    passCount++;
    console.log(`  PASS: ${message}`);
  } else {
    failCount++;
    console.log(`  FAIL: ${message}`);
  }
}

function assertEqual(actual, expected, message) {
  testCount++;
  if (actual === expected) {
    passCount++;
    console.log(`  PASS: ${message}`);
  } else {
    failCount++;
    console.log(`  FAIL: ${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`);
  }
}

let browser;
let context;

/**
 * Run *body* against a local server answering every request with *handler*.
 */
async function withServer(handler, body) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const page = await context.newPage();
  try {
    await body(page, base);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    await page.close();
  }
}

async function testNavigateOntoAnAuthRefusalFailsInsteadOfProceeding() {
  console.log('\n## Test: navigate onto an auth refusal fails loudly');
  // A token-gated server answers an unauthenticated request with a JSON
  // refusal body. Screenshotting that body yields a plausible-looking
  // capture of a screen nobody rendered, so the step must not proceed.
  await withServer((req, res) => {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end('{"error":{"code":"session_token_required"}}');
  }, async (page, base) => {
    const result = await executeStep(page, {
      route: '/',
      action: 'navigate',
    }, { baseUrl: base });

    assertEqual(result.success, false, 'navigate onto a 401 reports failure');
    assert(result.error.includes('401'), 'error names the refusing status');
    assert(
      result.error.includes('authentication refusal'),
      'error says the page is a refusal, not the requested screen',
    );
    assert(
      result.error.includes('snapshot screenshot'),
      'error names the recovery that establishes the session',
    );
  });
}

async function testNavigateOntoAMissingPageFailsAsRouteNotFound() {
  console.log('\n## Test: navigate onto a 404 fails as route_not_found');
  // A not-found page is still a rendered page: without this check the case
  // would fail later on a missing element, far from the wrong route.
  await withServer((req, res) => {
    res.writeHead(404, { 'Content-Type': 'text/html' });
    res.end('<!doctype html><title>Not found</title><h1>Page not found</h1>');
  }, async (page, base) => {
    const result = await executeStep(page, {
      route: '/workflows?project=1',
      action: 'navigate',
    }, { baseUrl: `${base}/?token=s3cret` });

    assertEqual(result.success, false, 'navigate onto a 404 reports failure');
    assert(
      result.error.startsWith('route_not_found:'),
      'error leads with the route_not_found reason',
    );
    assert(
      result.error.includes(`${base}/workflows?project=1`),
      'error names the URL the step navigated to',
    );
    assert(
      !result.error.includes('s3cret'),
      'error never quotes a credential carried by the base URL',
    );
    assert(
      result.error.includes('path prefix'),
      'error names the correction: route to a page the site serves',
    );
  });
}

async function testNavigateReturnsResponseStatus(status) {
  console.log(`\n## Test: navigate returns HTTP ${status}`);
  await withServer((req, res) => {
    res.writeHead(status, { 'Content-Type': 'text/html' });
    res.end('<!doctype html><title>Home</title><h1>Home</h1>');
  }, async (page, base) => {
    const result = await executeStep(page, {
      route: '/',
      action: 'navigate',
    }, { baseUrl: base });

    assertEqual(result.success, true, `navigate onto a ${status} completes`);
    assertEqual(result.status, status, 'result exposes the loaded response status');
  });
}

async function run() {
  console.log('=== Step Runner Tests: Navigate status ===');
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  try {
    await testNavigateOntoAnAuthRefusalFailsInsteadOfProceeding();
    await testNavigateOntoAMissingPageFailsAsRouteNotFound();
    await testNavigateReturnsResponseStatus(200);
    await testNavigateReturnsResponseStatus(503);
  } catch (err) {
    console.error('\nUnexpected error:', err);
    failCount++;
  } finally {
    await browser.close();
  }
  console.log(`\n=== Results: ${passCount}/${testCount} passed, ${failCount} failed ===`);
  if (failCount > 0) process.exit(1);
}

run();
