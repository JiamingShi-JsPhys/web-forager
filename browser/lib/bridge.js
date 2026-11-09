"use strict";

// Where the bridge command comes from.
//
// Order:
//   1. an explicit --bridge value,
//   2. WEB_FORAGER_BRIDGE when it is set (an empty value disables discovery,
//      which is what the tests use to exercise the no-bridge path),
//   3. the reference bridge that ships next to this file, if it exists.
//
// Step 3 is what makes a first run work without any configuration: the bridge
// lives in the same package as the playbooks, so requiring an environment
// variable to find it only produced a confusing `backend_unavailable`.

const fs = require("node:fs");
const path = require("node:path");

const BUNDLED_BRIDGE = path.join(__dirname, "..", "bridges", "playwright-bridge.js");

function bundledBridge() {
  try {
    return fs.existsSync(BUNDLED_BRIDGE) ? BUNDLED_BRIDGE : "";
  } catch (error) {
    return "";
  }
}

function quote(value) {
  return /\s/.test(value) ? `"${value}"` : value;
}

function resolveBridge(explicit) {
  const given = typeof explicit === "string" ? explicit.trim() : "";
  if (given) return given;

  const env = process.env.WEB_FORAGER_BRIDGE;
  if (env !== undefined) return env.trim();

  const bundled = bundledBridge();
  return bundled ? `node ${quote(bundled)}` : "";
}

module.exports = { BUNDLED_BRIDGE, bundledBridge, resolveBridge };
