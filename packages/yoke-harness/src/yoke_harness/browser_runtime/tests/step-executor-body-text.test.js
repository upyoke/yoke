'use strict';

/**
 * Tests for the scenario step executor — body-target text semantics.
 *
 * Run: node tests/step-executor-body-text.test.js
 *
 * Covers visible-text + hydration-aware semantics for ``target: "body"``
 * with ``check: "text_contains"`` and ``check: "text_equals"``. Companion
 * files cover non-body assertion checks and other actions.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { executeStep } = require('../src/step-executor');

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
let tmpDir;

async function setup() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'step-exec-test-'));
}

async function teardown() {
  if (browser) await browser.close();
  try {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  } catch (_) {
    // Ignore cleanup errors
  }
}

function fixtureUrl() {
  const fixturePath = path.join(__dirname, 'fixtures', 'test-page.html');
  return `file://${fixturePath}`;
}

function baseUrl() {
  const fixturesDir = path.join(__dirname, 'fixtures');
  return `file://${fixturesDir}`;
}

async function testTextContainsBodyExcludesScriptContent() {
  console.log('\n## Test: text_contains on body target excludes RSC script content');
  const page = await context.newPage();
  const rscFixtureUrl = `file://${path.join(__dirname, 'fixtures', 'rsc-page.html')}`;
  await page.goto(rscFixtureUrl, { waitUntil: 'domcontentloaded' });

  // The page has "RACING" in visible text AND RSC flight data in <script> tags.
  // text_contains with body target should find "racing" in visible text only.
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'body',
    check: 'text_contains',
    expected: 'racing',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'text_contains on body finds visible "racing" text');

  // Verify that RSC flight data strings are NOT included in the text search.
  // "__next_f" exists in script tags but should not appear in visible text.
  const rscResult = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'body',
    check: 'text_contains',
    expected: '__next_f',
  }, { baseUrl: baseUrl() });

  assertEqual(rscResult.success, false, 'text_contains on body does NOT find script-only "__next_f"');

  await page.close();
}

async function testTextContainsBodyHydrationWait() {
  console.log('\n## Test: text_contains on body waits for hydration-delayed content');
  const page = await context.newPage();
  const hydrationFixtureUrl = `file://${path.join(__dirname, 'fixtures', 'hydration-delayed.html')}`;
  await page.goto(hydrationFixtureUrl, { waitUntil: 'domcontentloaded' });

  // The page starts with a visible "Loading..." shell, then swaps in the
  // hydrated content after 500ms. Document-wide assertions must keep polling
  // until the expected text appears instead of returning on the first visible text.
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'body',
    check: 'text_contains',
    expected: 'hydrated content',
    timeout_ms: 3000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'text_contains on body finds hydration-delayed text');

  await page.close();
}

async function testTextContainsNonBodyUsesNormalSemantics() {
  console.log('\n## Test: text_contains on non-body target uses normal locator semantics');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // Non-body target (h1) should use standard textContent() — not the visible-text path
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'h1',
    check: 'text_contains',
    expected: 'Test Page',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'text_contains on h1 (non-body) still works normally');

  // Non-matching text on non-body target should still fail
  const result2 = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'h1',
    check: 'text_contains',
    expected: 'nonexistent',
  }, { baseUrl: baseUrl() });

  assertEqual(result2.success, false, 'text_contains on h1 with non-matching text fails');

  await page.close();
}

async function testTextEqualsBodyExcludesScriptContent() {
  console.log('\n## Test: text_equals on body target uses visible-text path');
  const page = await context.newPage();
  // Use a simple page with known body text and a script tag
  await page.setContent('<!doctype html><html><body><p>Hello World</p><script>var x = "secret";</script></body></html>');

  // text_equals on body should compare against visible text only
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'body',
    check: 'text_equals',
    expected: 'Hello World',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'text_equals on body matches visible text, excludes script content');

  await page.close();
}

async function testTextContainsBodyErrorOutputBounded() {
  console.log('\n## Test: text_contains failure on body produces bounded error output');
  const page = await context.newPage();
  const rscFixtureUrl = `file://${path.join(__dirname, 'fixtures', 'rsc-page.html')}`;
  await page.goto(rscFixtureUrl, { waitUntil: 'domcontentloaded' });

  // Search for text that does not exist — error message should be bounded
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'body',
    check: 'text_contains',
    expected: 'nonexistent text that is not on this page',
    timeout_ms: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'text_contains for missing text fails');
  assert(result.error.length < 500, `error message is bounded (${result.error.length} chars)`);
  assert(!result.error.includes('__next_f'), 'error does not contain RSC flight data');

  await page.close();
}

async function testTextContainsBodyCaseInsensitive() {
  console.log('\n## Test: text_contains on body preserves case-insensitive matching');
  const page = await context.newPage();
  const rscFixtureUrl = `file://${path.join(__dirname, 'fixtures', 'rsc-page.html')}`;
  await page.goto(rscFixtureUrl, { waitUntil: 'domcontentloaded' });

  // "RACING" is in the page; searching for "racing" (lowercase) should match
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'body',
    check: 'text_contains',
    expected: 'racing',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'case-insensitive text_contains on body works');

  // Also test with mixed case
  const result2 = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'body',
    check: 'text_contains',
    expected: 'Racing',
  }, { baseUrl: baseUrl() });

  assertEqual(result2.success, true, 'mixed-case text_contains on body works');

  await page.close();
}

async function run() {
  console.log('=== Step Executor Tests: Body-Target Text ===');
  await setup();
  try {
    await testTextContainsBodyExcludesScriptContent();
    await testTextContainsBodyHydrationWait();
    await testTextContainsNonBodyUsesNormalSemantics();
    await testTextEqualsBodyExcludesScriptContent();
    await testTextContainsBodyErrorOutputBounded();
    await testTextContainsBodyCaseInsensitive();
  } catch (err) {
    console.error('\nUnexpected error:', err);
    failCount++;
  } finally {
    await teardown();
  }
  console.log(`\n=== Results: ${passCount}/${testCount} passed, ${failCount} failed ===`);
  if (failCount > 0) process.exit(1);
}

run();
