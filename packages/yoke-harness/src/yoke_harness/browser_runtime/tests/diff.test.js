'use strict';

/**
 * Tests for diff snapshot primitive.
 *
 * Run: node tests/diff.test.js
 *
 * Tests use a local HTML fixture and real Playwright browser instance.
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { chromium } = require('playwright');
const { PNG } = require('pngjs');
const { diffScreenshot } = require('../src/diff');

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

/**
 * Create a solid-color PNG file for testing.
 * @param {string} filePath
 * @param {number} width
 * @param {number} height
 * @param {{ r: number, g: number, b: number }} color
 */
function createSolidPng(filePath, width, height, color) {
  const png = new PNG({ width, height });
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = (png.width * y + x) << 2;
      png.data[idx] = color.r;
      png.data[idx + 1] = color.g;
      png.data[idx + 2] = color.b;
      png.data[idx + 3] = 255;
    }
  }
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(filePath, PNG.sync.write(png));
}

// ---------------------------------------------------------------------------
// Test context
// ---------------------------------------------------------------------------

let browser;
let context;
let tmpDir;

async function setup() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yoke-diff-test-'));
}

async function teardown() {
  if (browser) await browser.close();
  // Clean up temp dir
  if (tmpDir && fs.existsSync(tmpDir)) {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

function fixtureUrl() {
  const fixturePath = path.join(__dirname, 'fixtures', 'test-page.html');
  return `file://${fixturePath}`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

async function testDiffAgainstIdenticalBaseline() {
  console.log('\n## Test: Diff against identical baseline produces diff_pct ~= 0');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const viewport = { width: 800, height: 600 };

  // First capture a baseline by taking a screenshot
  const baselinePath = path.join(tmpDir, 'identical-baseline.png');
  await page.setViewportSize(viewport);
  await page.screenshot({ path: baselinePath, fullPage: false });

  // Now diff against that same page (should be near-identical)
  const result = await diffScreenshot(page, {
    baselinePath,
    viewport,
    outputDir: tmpDir,
  });

  assert(typeof result.diff_pct === 'number', 'diff_pct is a number');
  assert(result.diff_pct <= 1, `diff_pct is near zero (got ${result.diff_pct})`);
  assertEqual(result.missing_baseline, false, 'missing_baseline is false');
  assert(fs.existsSync(result.candidate_path), 'candidate file exists');
  assert(fs.existsSync(result.diff_image_path), 'diff image file exists');
  assertEqual(result.baseline_path, baselinePath, 'baseline_path matches input');
  assertEqual(result.viewport.width, 800, 'viewport width matches');
  assertEqual(result.viewport.height, 600, 'viewport height matches');

  await page.close();
}

async function testDiffAgainstDifferentBaseline() {
  console.log('\n## Test: Diff against different baseline produces diff_pct > 0');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const viewport = { width: 100, height: 100 };

  // Create a solid blue baseline that will differ from the page screenshot
  const baselinePath = path.join(tmpDir, 'different-baseline.png');
  createSolidPng(baselinePath, 100, 100, { r: 0, g: 0, b: 255 });

  const result = await diffScreenshot(page, {
    baselinePath,
    viewport,
    outputDir: tmpDir,
  });

  assert(typeof result.diff_pct === 'number', 'diff_pct is a number');
  assert(result.diff_pct > 0, `diff_pct is > 0 (got ${result.diff_pct})`);
  assert(result.diff_pct <= 100, `diff_pct is <= 100 (got ${result.diff_pct})`);
  assertEqual(result.missing_baseline, false, 'missing_baseline is false');
  assert(fs.existsSync(result.diff_image_path), 'diff image file exists');

  // Verify diff image is a valid PNG
  const diffPng = PNG.sync.read(fs.readFileSync(result.diff_image_path));
  assertEqual(diffPng.width, 100, 'diff image width matches viewport');
  assertEqual(diffPng.height, 100, 'diff image height matches viewport');

  await page.close();
}

async function testMissingBaseline() {
  console.log('\n## Test: Missing baseline returns missing_baseline: true');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const nonexistentPath = path.join(tmpDir, 'does-not-exist.png');
  const viewport = { width: 400, height: 300 };

  const result = await diffScreenshot(page, {
    baselinePath: nonexistentPath,
    viewport,
    outputDir: tmpDir,
  });

  assertEqual(result.diff_pct, null, 'diff_pct is null');
  assertEqual(result.missing_baseline, true, 'missing_baseline is true');
  assert(typeof result.candidate_path === 'string', 'candidate_path is a string');
  assert(fs.existsSync(result.candidate_path), 'candidate file was still captured');
  assertEqual(result.baseline_path, nonexistentPath, 'baseline_path matches input');
  assertEqual(result.diff_image_path, '', 'diff_image_path is empty string');
  assertEqual(result.viewport.width, 400, 'viewport width matches');
  assertEqual(result.viewport.height, 300, 'viewport height matches');

  await page.close();
}

async function testViewportDimensionsApplied() {
  console.log('\n## Test: Viewport dimensions are applied correctly');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // Use a non-standard viewport size
  const viewport = { width: 640, height: 480 };
  const baselinePath = path.join(tmpDir, 'nonexistent-for-viewport-test.png');

  const result = await diffScreenshot(page, {
    baselinePath,
    viewport,
    outputDir: tmpDir,
  });

  // Since baseline is missing, we just check the candidate was captured at the right size
  assertEqual(result.viewport.width, 640, 'viewport width in result matches');
  assertEqual(result.viewport.height, 480, 'viewport height in result matches');

  // Verify candidate screenshot dimensions
  const candidatePng = PNG.sync.read(fs.readFileSync(result.candidate_path));
  assertEqual(candidatePng.width, 640, 'candidate PNG width matches viewport');
  assertEqual(candidatePng.height, 480, 'candidate PNG height matches viewport');

  await page.close();
}

async function testOutputFilePaths() {
  console.log('\n## Test: Output file paths are correct');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const outputDir = path.join(tmpDir, 'custom-output');
  const viewport = { width: 200, height: 200 };

  // Create a baseline in the output dir
  const baselinePath = path.join(outputDir, 'test-baseline.png');
  createSolidPng(baselinePath, 200, 200, { r: 128, g: 128, b: 128 });

  const result = await diffScreenshot(page, {
    baselinePath,
    viewport,
    outputDir,
  });

  // candidate and diff should be in the custom output dir
  assert(result.candidate_path.startsWith(outputDir), 'candidate_path is in outputDir');
  assert(result.diff_image_path.startsWith(outputDir), 'diff_image_path is in outputDir');
  assert(result.candidate_path.endsWith('.png'), 'candidate_path ends with .png');
  assert(result.diff_image_path.endsWith('.png'), 'diff_image_path ends with .png');

  await page.close();
}

async function testThresholdConfigurable() {
  console.log('\n## Test: Anti-aliasing threshold is configurable');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const viewport = { width: 100, height: 100 };

  // Create a slightly different baseline (near-match gray vs the actual page)
  const baselinePath = path.join(tmpDir, 'threshold-baseline.png');
  await page.setViewportSize(viewport);
  await page.screenshot({ path: baselinePath, fullPage: false });

  // Diff with very strict threshold (0.01)
  const strictResult = await diffScreenshot(page, {
    baselinePath,
    viewport,
    outputDir: tmpDir,
    threshold: 0.01,
  });

  // Diff with very lenient threshold (0.9)
  const lenientResult = await diffScreenshot(page, {
    baselinePath,
    viewport,
    outputDir: tmpDir,
    threshold: 0.9,
  });

  assert(typeof strictResult.diff_pct === 'number', 'strict diff_pct is a number');
  assert(typeof lenientResult.diff_pct === 'number', 'lenient diff_pct is a number');
  // Lenient threshold should report same or fewer diffs than strict
  assert(
    lenientResult.diff_pct <= strictResult.diff_pct,
    `lenient diff_pct (${lenientResult.diff_pct}) <= strict diff_pct (${strictResult.diff_pct})`
  );

  await page.close();
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

async function run() {
  console.log('# Diff Snapshot Tests\n');

  try {
    await setup();
  } catch (err) {
    console.error('Setup failed:', err.message);
    console.error('Make sure Playwright browsers are installed: npx playwright install chromium');
    process.exit(1);
  }

  const tests = [
    testDiffAgainstIdenticalBaseline,
    testDiffAgainstDifferentBaseline,
    testMissingBaseline,
    testViewportDimensionsApplied,
    testOutputFilePaths,
    testThresholdConfigurable,
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
