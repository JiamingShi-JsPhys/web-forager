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

// The bridge command is executed directly, never through a shell. Split it on
// whitespace, keeping quoted paths together; backslashes are literal so a
// Windows path is not mistaken for an escape. Shell operators (pipes, `&&`,
// redirections) are therefore not interpreted.
function splitCommand(command) {
  const text = String(command == null ? "" : command).trim();
  if (!text) return [];
  const parts = [];
  let current = "";
  let quoted = "";
  let started = false;
  for (const char of text) {
    if (quoted) {
      if (char === quoted) quoted = "";
      else current += char;
      continue;
    }
    if (char === '"' || char === "'") {
      quoted = char;
      started = true;
      continue;
    }
    if (/\s/.test(char)) {
      if (started) {
        parts.push(current);
        current = "";
        started = false;
      }
      continue;
    }
    current += char;
    started = true;
  }
  if (quoted) {
    throw new Error(`unterminated ${quoted} quote in the bridge command`);
  }
  if (started) parts.push(current);
  return parts;
}

function resolveBridge(explicit) {
  const given = typeof explicit === "string" ? explicit.trim() : "";
  if (given) return given;

  const env = process.env.WEB_FORAGER_BRIDGE;
  if (env !== undefined) return env.trim();

  const bundled = bundledBridge();
  return bundled ? `node ${quote(bundled)}` : "";
}

module.exports = { BUNDLED_BRIDGE, bundledBridge, resolveBridge, splitCommand };
