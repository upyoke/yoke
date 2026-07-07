'use strict';

/**
 * Route module for snapshot operations.
 *
 * Registers:
 *   POST /api/snapshot/accessibility
 *   POST /api/snapshot/screenshot
 *   POST /api/snapshot/diff
 *
 * Follows the route registration pattern from task 001 GAP #3:
 *   module.exports = function(app, browserManager) { ... }
 */

const { accessibilitySnapshot, buildRefMap } = require('../snapshot');
const { annotatedScreenshot, plainScreenshot } = require('../screenshot');
const { diffScreenshot } = require('../diff');

/**
 * @param {import('express').Application} app
 * @param {Object} browserManager
 */
function registerSnapshotRoutes(app, browserManager) {
  // POST /api/snapshot/accessibility
  // Request body: { url?: string }
  // Response: { success: true, data: { tree, refs, url, timestamp } }
  app.post('/api/snapshot/accessibility', async (req, res) => {
    try {
      const { url } = req.body || {};

      // AC-6: If no URL is provided, captures the current page state
      const page = await browserManager.getPage(url || undefined);

      const result = await accessibilitySnapshot(page);

      res.json({
        success: true,
        data: result,
      });
    } catch (err) {
      res.status(500).json({
        success: false,
        error: err.message,
      });
    }
  });

  // POST /api/snapshot/screenshot
  // Request body: { url?: string, annotate?: boolean, outputPath?: string, viewport?: { width, height } }
  // Response: { success: true, data: { imagePath, refs?, url, timestamp, viewport } }
  app.post('/api/snapshot/screenshot', async (req, res) => {
    try {
      const { url, annotate, outputPath, viewport } = req.body || {};

      const page = await browserManager.getPage(url || undefined);
      const options = {};
      if (outputPath) options.outputPath = outputPath;
      if (viewport) options.viewport = viewport;

      let result;
      if (annotate) {
        // AC-1: Build ref map and capture annotated screenshot
        const refMap = await buildRefMap(page);
        result = await annotatedScreenshot(page, refMap, options);
      } else {
        // AC-3: Plain screenshot without badges
        result = await plainScreenshot(page, options);
      }

      res.json({
        success: true,
        data: result,
      });
    } catch (err) {
      res.status(500).json({
        success: false,
        error: err.message,
      });
    }
  });
  // POST /api/snapshot/diff
  // Request body: { url?: string, baselinePath: string, viewport: { width, height }, outputDir?: string, threshold?: number }
  // Response: { success: true, data: { diff_pct, diff_image_path, candidate_path, baseline_path, viewport, missing_baseline } }
  app.post('/api/snapshot/diff', async (req, res) => {
    try {
      const { url, baselinePath, viewport, outputDir, threshold } = req.body || {};

      if (!baselinePath) {
        return res.status(400).json({
          success: false,
          error: 'baselinePath is required',
        });
      }
      if (!viewport || !viewport.width || !viewport.height) {
        return res.status(400).json({
          success: false,
          error: 'viewport with width and height is required',
        });
      }

      const page = await browserManager.getPage(url || undefined);

      const diffOptions = { baselinePath, viewport };
      if (outputDir) diffOptions.outputDir = outputDir;
      if (threshold !== undefined) diffOptions.threshold = threshold;

      const result = await diffScreenshot(page, diffOptions);

      res.json({
        success: true,
        data: result,
      });
    } catch (err) {
      res.status(500).json({
        success: false,
        error: err.message,
      });
    }
  });
}

module.exports = registerSnapshotRoutes;
