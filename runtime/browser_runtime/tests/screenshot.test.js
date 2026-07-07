'use strict';

/**
 * Tests for annotated screenshot with ref badges.
 *
 * Run: node tests/screenshot.test.js
 *
 * Tests use a local HTML fixture and real Playwright browser instance.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { annotatedScreenshot, plainScreenshot } = require('../src/screenshot');
const { buildRefMap } = require('../src/snapshot');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Test context
// ---------------------------------------------------------------------------

let browser;
let context;
const tmpFiles = [];

async function setup() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
}

async function teardown() {
  if (browser) await browser.close();
  // Clean up temp files
  for (const f of tmpFiles) {
    try { fs.unlinkSync(f); } catch (_) { /* ignore */ }
  }
}

function fixtureUrl() {
  const fixturePath = path.join(__dirname, 'fixtures', 'test-page.html');
  return `file://${fixturePath}`;
}

function tmpPath(suffix) {
  const p = path.join(os.tmpdir(), `yoke-test-screenshot-${Date.now()}-${process.pid}${suffix || '.png'}`);
  tmpFiles.push(p);
  return p;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

async function testAnnotatedScreenshotProducesPng() {
  console.log('\n## Test: Annotated screenshot produces a PNG file');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const refMap = await buildRefMap(page);
  const outPath = tmpPath();
  const result = await annotatedScreenshot(page, refMap, { outputPath: outPath });

  assert(fs.existsSync(result.imagePath), 'PNG file exists at imagePath');
  const stat = fs.statSync(result.imagePath);
  assert(stat.size > 0, 'PNG file is non-empty');

  // Verify it starts with PNG magic bytes
  const buf = Buffer.alloc(8);
  const fd = fs.openSync(result.imagePath, 'r');
  fs.readSync(fd, buf, 0, 8, 0);
  fs.closeSync(fd);
  assert(buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4E && buf[3] === 0x47, 'File has PNG magic bytes');

  await page.close();
}

async function testAnnotatedScreenshotResponseShape() {
  console.log('\n## Test: Annotated screenshot response matches contract');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const refMap = await buildRefMap(page);
  const outPath = tmpPath();
  const result = await annotatedScreenshot(page, refMap, { outputPath: outPath });

  // AC-2: Response includes imagePath, refs, url, timestamp, viewport
  assert(typeof result.imagePath === 'string', 'imagePath is a string');
  assert(typeof result.refs === 'object' && result.refs !== null, 'refs is an object');
  assert(typeof result.url === 'string', 'url is a string');
  assert(typeof result.timestamp === 'string', 'timestamp is a string');
  assert(!isNaN(Date.parse(result.timestamp)), 'timestamp is valid ISO date');
  assert(typeof result.viewport === 'object', 'viewport is an object');
  assert(typeof result.viewport.width === 'number', 'viewport.width is a number');
  assert(typeof result.viewport.height === 'number', 'viewport.height is a number');

  // Ref map keys should exist
  const keys = Object.keys(result.refs);
  assert(keys.length > 0, 'refs map is not empty');

  await page.close();
}

async function testRefMapMatchesRefIds() {
  console.log('\n## Test: Ref map in response matches ref IDs from buildRefMap');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const refMap = await buildRefMap(page);
  const outPath = tmpPath();
  const result = await annotatedScreenshot(page, refMap, { outputPath: outPath });

  // The refs in the response should be the same refMap we passed in
  const origKeys = Object.keys(refMap).sort();
  const resultKeys = Object.keys(result.refs).sort();
  assertEqual(origKeys.length, resultKeys.length, 'Same number of refs');
  let allMatch = true;
  for (let i = 0; i < origKeys.length; i++) {
    if (origKeys[i] !== resultKeys[i] || refMap[origKeys[i]] !== result.refs[resultKeys[i]]) {
      allMatch = false;
    }
  }
  assert(allMatch, 'All ref ID -> locator mappings match');

  await page.close();
}

async function testPlainScreenshotNoBadges() {
  console.log('\n## Test: Plain screenshot (annotate=false) produces smaller or equal file (heuristic)');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const refMap = await buildRefMap(page);

  const plainPath = tmpPath('-plain.png');
  const annotatedPath = tmpPath('-annotated.png');

  await plainScreenshot(page, { outputPath: plainPath });
  await annotatedScreenshot(page, refMap, { outputPath: annotatedPath });

  const plainSize = fs.statSync(plainPath).size;
  const annotatedSize = fs.statSync(annotatedPath).size;

  assert(plainSize > 0, 'Plain screenshot is non-empty');
  assert(annotatedSize > 0, 'Annotated screenshot is non-empty');
  // Annotated should generally be larger due to badge overlays, but at minimum both exist
  // We use a loose heuristic: annotated should differ from plain
  assert(plainSize !== annotatedSize, 'Plain and annotated screenshots differ in size (badge presence heuristic)');

  // Plain result should NOT have refs field
  const plainResult = await plainScreenshot(page, { outputPath: tmpPath('-plain2.png') });
  assert(plainResult.refs === undefined, 'Plain screenshot response has no refs field');

  await page.close();
}

async function testCustomOutputPath() {
  console.log('\n## Test: Custom output path is respected');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const customPath = tmpPath('-custom.png');
  const result = await plainScreenshot(page, { outputPath: customPath });

  assertEqual(result.imagePath, customPath, 'imagePath matches the custom output path');
  assert(fs.existsSync(customPath), 'File exists at custom path');

  await page.close();
}

async function testPageUnchangedAfterScreenshot() {
  console.log('\n## Test: Page state is unchanged after annotated screenshot (no residual overlays)');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // Take a snapshot of DOM element count before
  const countBefore = await page.evaluate(() => document.body.querySelectorAll('*').length);

  const refMap = await buildRefMap(page);
  await annotatedScreenshot(page, refMap, { outputPath: tmpPath() });

  // AC-5: Check that no residual overlay elements remain
  const countAfter = await page.evaluate(() => document.body.querySelectorAll('*').length);
  assertEqual(countAfter, countBefore, 'DOM element count unchanged after screenshot');

  // Specifically check that the badge container is gone
  const containerExists = await page.evaluate(() => !!document.getElementById('__yoke_badge_container__'));
  assert(!containerExists, 'Badge container element is removed');

  await page.close();
}

async function testDefaultOutputPath() {
  console.log('\n## Test: Default output path writes to temp directory');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await plainScreenshot(page);
  tmpFiles.push(result.imagePath); // track for cleanup

  assert(result.imagePath.includes(os.tmpdir()), 'Default path is in temp directory');
  assert(fs.existsSync(result.imagePath), 'File exists at default path');

  await page.close();
}

async function testViewportDimensionsInResponse() {
  console.log('\n## Test: Screenshot metadata includes viewport dimensions');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await plainScreenshot(page, { outputPath: tmpPath() });

  // AC-7: viewport dimensions in response
  assert(result.viewport.width > 0, 'viewport width is positive');
  assert(result.viewport.height > 0, 'viewport height is positive');

  await page.close();
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

async function run() {
  console.log('# Screenshot Tests\n');

  try {
    await setup();
  } catch (err) {
    console.error('Setup failed:', err.message);
    console.error('Make sure Playwright browsers are installed: npx playwright install chromium');
    process.exit(1);
  }

  const tests = [
    testAnnotatedScreenshotProducesPng,
    testAnnotatedScreenshotResponseShape,
    testRefMapMatchesRefIds,
    testPlainScreenshotNoBadges,
    testCustomOutputPath,
    testPageUnchangedAfterScreenshot,
    testDefaultOutputPath,
    testViewportDimensionsInResponse,
  ];

  for (const test of tests) {
    try {
      await test();
    } catch (err) {
      testCount++;
      failCount++;
      console.log(`  FAIL: ${test.name} threw: ${err.message}`);
    }
  }

  await teardown();

  console.log(`\n---\nResults: ${passCount}/${testCount} passed, ${failCount} failed`);
  process.exit(failCount > 0 ? 1 : 0);
}

run();
