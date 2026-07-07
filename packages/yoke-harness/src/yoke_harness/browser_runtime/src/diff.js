'use strict';

/**
 * Diffable snapshot against a baseline image.
 *
 * Exports:
 *   diffScreenshot(page, options) -> {
 *     diff_pct: number|null,
 *     diff_image_path: string,
 *     candidate_path: string,
 *     baseline_path: string,
 *     viewport: { width, height },
 *     missing_baseline: boolean
 *   }
 *
 * Uses pixelmatch for pixel-level comparison and pngjs for PNG I/O.
 * When no baseline exists, captures the candidate and returns
 * { diff_pct: null, missing_baseline: true }.
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { PNG } = require('pngjs');
const pixelmatch = require('pixelmatch');

/**
 * Generate a temp file path for a diff artifact.
 * @param {string} suffix - e.g. 'candidate', 'diff'
 * @returns {string}
 */
function tempPath(suffix) {
  const ts = Date.now();
  return path.join(os.tmpdir(), `yoke-diff-${suffix}-${ts}-${process.pid}.png`);
}

/**
 * Read a PNG file and return a pngjs PNG object.
 * @param {string} filePath
 * @returns {Promise<PNG>}
 */
function readPng(filePath) {
  return new Promise((resolve, reject) => {
    const stream = fs.createReadStream(filePath).pipe(new PNG());
    stream.on('parsed', function () {
      resolve(this);
    });
    stream.on('error', reject);
  });
}

/**
 * Write a pngjs PNG object to a file.
 * @param {PNG} png
 * @param {string} filePath
 * @returns {Promise<void>}
 */
function writePng(png, filePath) {
  return new Promise((resolve, reject) => {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    const stream = png.pack().pipe(fs.createWriteStream(filePath));
    stream.on('finish', resolve);
    stream.on('error', reject);
  });
}

/**
 * Capture a screenshot and diff it against a baseline image.
 *
 * Baseline composite key groups screenshots by project, route slug, and viewport:
 *   {project}/{route_slug}/{width}x{height}
 * Route slug derivation: replace `/` with `-`, strip leading `-`.
 *
 * @param {import('playwright').Page} page - Playwright page (already navigated or will navigate via caller)
 * @param {Object} options
 * @param {string} options.baselinePath - Absolute path to the baseline PNG
 * @param {{ width: number, height: number }} options.viewport - Viewport dimensions for capture
 * @param {string} [options.outputDir] - Directory for candidate and diff images; defaults to os.tmpdir()
 * @param {number} [options.threshold=0.1] - Anti-aliasing threshold for pixelmatch (0-1)
 * @returns {Promise<{
 *   diff_pct: number|null,
 *   diff_image_path: string,
 *   candidate_path: string,
 *   baseline_path: string,
 *   viewport: { width: number, height: number },
 *   missing_baseline: boolean
 * }>}
 */
async function diffScreenshot(page, options) {
  const { baselinePath, viewport, outputDir, threshold = 0.1 } = options;

  if (!baselinePath) {
    throw new Error('baselinePath is required');
  }
  if (!viewport || !viewport.width || !viewport.height) {
    throw new Error('viewport with width and height is required');
  }

  // AC-5: Set viewport before capture
  await page.setViewportSize({ width: viewport.width, height: viewport.height });

  // Determine output paths
  const outDir = outputDir || os.tmpdir();
  const ts = Date.now();
  const candidatePath = path.join(outDir, `candidate-${ts}-${process.pid}.png`);
  const diffImagePath = path.join(outDir, `diff-${ts}-${process.pid}.png`);

  // Ensure output directory exists
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  // Capture candidate screenshot
  await page.screenshot({ path: candidatePath, fullPage: false });

  // AC-4: When baseline does not exist, return missing_baseline
  if (!fs.existsSync(baselinePath)) {
    return {
      diff_pct: null,
      diff_image_path: '',
      candidate_path: candidatePath,
      baseline_path: baselinePath,
      viewport: { width: viewport.width, height: viewport.height },
      missing_baseline: true,
    };
  }

  // Read baseline and candidate PNGs
  const baselinePng = await readPng(baselinePath);
  const candidatePng = await readPng(candidatePath);

  const { width, height } = baselinePng;

  // If dimensions mismatch, resize candidate conceptually by comparing
  // at the minimum overlapping area -- but per spec we set viewport to
  // match baseline dimensions, so this should be rare.
  const compareWidth = Math.min(width, candidatePng.width);
  const compareHeight = Math.min(height, candidatePng.height);

  // Create diff output PNG
  const diffPng = new PNG({ width: compareWidth, height: compareHeight });

  // AC-2: Diff image highlights changed pixels (pixelmatch default: red/magenta overlay)
  // AC-6: Anti-aliasing threshold is configurable
  const numDiffPixels = pixelmatch(
    baselinePng.data,
    candidatePng.data,
    diffPng.data,
    compareWidth,
    compareHeight,
    {
      threshold,
      includeAA: false,
      diffColor: [255, 0, 128],      // Magenta for diff pixels
      diffColorAlt: [255, 50, 50],    // Red for anti-aliased diff pixels
    }
  );

  // Write diff image
  await writePng(diffPng, diffImagePath);

  // AC-3: Calculate diff percentage
  const totalPixels = compareWidth * compareHeight;
  const diffPct = totalPixels > 0 ? (numDiffPixels / totalPixels) * 100 : 0;

  return {
    diff_pct: Math.round(diffPct * 100) / 100, // Round to 2 decimal places
    diff_image_path: diffImagePath,
    candidate_path: candidatePath,
    baseline_path: baselinePath,
    viewport: { width: viewport.width, height: viewport.height },
    missing_baseline: false,
  };
}

module.exports = { diffScreenshot };
