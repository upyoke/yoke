'use strict';

/**
 * Tests that a screenshot step naming a target frames that element rather
 * than the viewport: the capture is the element's own box, and an element
 * below the fold is scrolled to instead of being missed.
 *
 * Run: node tests/step-runner-capture-target.test.js
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { PNG } = require('pngjs');
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
    console.log(
      `  FAIL: ${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`
    );
  }
}

let browser;
let context;
let outputDir;

const VIEWPORT = { width: 800, height: 400 };

function baseUrl() {
  return `file://${path.join(__dirname, 'fixtures')}`;
}

function imageSize(file) {
  const png = PNG.sync.read(fs.readFileSync(file));
  return { width: png.width, height: png.height };
}

async function openCards(page) {
  await page.setViewportSize(VIEWPORT);
  await page.goto(`${baseUrl()}/repeated-cards.html`);
}

async function testFullPageIsViewportBoundedHere() {
  console.log('\n## Test: fullPage is bounded by the viewport on this page');
  const page = await context.newPage();
  await openCards(page);

  // The list is 6 cards of 200px inside a 300px scroller, so the container's
  // content is far taller than the viewport while the container is not.
  const scrollHeight = await page.evaluate(
    () => document.getElementById('scroller').scrollHeight
  );
  assert(
    scrollHeight > VIEWPORT.height,
    `the container scrolls ${scrollHeight}px, past the ${VIEWPORT.height}px viewport`
  );

  const fullPage = await executeStep(page, {
    action: 'screenshot',
    capture: true,
    fullPage: true,
    label: 'full-page',
  }, { baseUrl: baseUrl(), outputDir });

  assertEqual(fullPage.success, true, 'the fullPage capture succeeds');
  const size = imageSize(fullPage.artifacts[0]);
  assertEqual(
    size.width,
    VIEWPORT.width,
    'fullPage is the viewport width'
  );
  assert(
    size.height > VIEWPORT.height,
    `fullPage grows with the document (${size.height}px), which is why it `
    + 'cannot frame one panel'
  );
  await page.close();
}

async function testTargetFramesTheElementBox() {
  console.log('\n## Test: a targeted capture frames the element, not the screen');
  const page = await context.newPage();
  await openCards(page);

  const box = await page.evaluate(() => {
    const rect = document.getElementById('scroller').getBoundingClientRect();
    return { width: Math.round(rect.width), height: Math.round(rect.height) };
  });

  const targeted = await executeStep(page, {
    action: 'screenshot',
    capture: true,
    target: '#scroller',
    label: 'scroller',
  }, { baseUrl: baseUrl(), outputDir });

  assertEqual(targeted.success, true, 'the targeted capture succeeds');
  assertEqual(
    targeted.artifacts.length,
    1,
    'the targeted capture reports one artifact'
  );
  const size = imageSize(targeted.artifacts[0]);
  assertEqual(size.height, box.height, 'the capture is the element box height');
  assertEqual(size.width, box.width, 'the capture is the element box width');
  assert(
    size.height < VIEWPORT.height,
    `the capture is the panel (${size.height}px), not the viewport `
    + `(${VIEWPORT.height}px)`
  );
  await page.close();
}

async function testTargetBelowTheFoldIsScrolledTo() {
  console.log('\n## Test: a target below the fold is scrolled to and captured');
  const page = await context.newPage();
  await openCards(page);

  const startedOffscreen = await page.evaluate(() => {
    const rect = document.getElementById('below-fold').getBoundingClientRect();
    return rect.top > window.innerHeight;
  });
  assert(startedOffscreen, 'the target starts below the viewport fold');

  const targeted = await executeStep(page, {
    action: 'screenshot',
    capture: true,
    target: '#below-fold',
    label: 'below fold',
  }, { baseUrl: baseUrl(), outputDir });

  assertEqual(targeted.success, true, 'the below-fold capture succeeds');
  const size = imageSize(targeted.artifacts[0]);
  assertEqual(size.height, 150, 'the below-fold element is captured at its own height');
  await page.close();
}

async function testTargetCaptureNamesTheLabel() {
  console.log('\n## Test: a targeted capture still honours label');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'screenshot',
    capture: true,
    target: '.card',
    label: 'one card',
  }, { baseUrl: baseUrl(), outputDir });

  assertEqual(result.success, true, 'a many-match target captures the first');
  assert(
    path.basename(result.artifacts[0]).startsWith('screenshot-one-card-'),
    `the label names the file (got ${path.basename(result.artifacts[0])})`
  );
  await page.close();
}

async function testMissingTargetFails() {
  console.log('\n## Test: a capture naming an absent target fails loudly');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'screenshot',
    capture: true,
    target: '#no-such-container',
    timeout_ms: 500,
  }, { baseUrl: baseUrl(), outputDir });

  assertEqual(
    result.success,
    false,
    'the step fails rather than recording a viewport screenshot instead'
  );
  await page.close();
}

async function testCaptureFalseStillSkips() {
  console.log('\n## Test: capture:false with a target records nothing');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'screenshot',
    capture: false,
    target: '#scroller',
  }, { baseUrl: baseUrl(), outputDir });

  assertEqual(result.success, true, 'the step succeeds');
  assertEqual(result.artifacts, undefined, 'no artifact is recorded');
  await page.close();
}

async function run() {
  console.log('=== Step Runner Tests: Capture Target ===');
  outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yoke-capture-target-'));
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  try {
    await testFullPageIsViewportBoundedHere();
    await testTargetFramesTheElementBox();
    await testTargetBelowTheFoldIsScrolledTo();
    await testTargetCaptureNamesTheLabel();
    await testMissingTargetFails();
    await testCaptureFalseStillSkips();
  } catch (err) {
    console.error('\nUnexpected error:', err);
    failCount++;
  } finally {
    if (browser) await browser.close();
  }
  console.log(`\n=== Results: ${passCount}/${testCount} passed, ${failCount} failed ===`);
  if (failCount > 0) process.exit(1);
}

run();
