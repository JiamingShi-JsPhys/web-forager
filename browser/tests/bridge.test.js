"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { splitCommand } = require("../lib/bridge");
const { BridgeBackend } = require("../lib/backend");

const FIXTURES = path.join(__dirname, "fixtures");
const FAKE = path.join(FIXTURES, "fake-bridge.js");

test("a quoted command keeps paths with spaces together", () => {
  assert.deepEqual(splitCommand(`"C:\\Program Files\\node.exe" "bridge file.js" --flag`), [
    "C:\\Program Files\\node.exe",
    "bridge file.js",
    "--flag",
  ]);
});

test("backslashes are literal, not escapes", () => {
  assert.deepEqual(splitCommand("node C:\\tools\\bridge.js"), ["node", "C:\\tools\\bridge.js"]);
});

test("single quotes group an argument too", () => {
  assert.deepEqual(splitCommand("node 'a b/c.js'"), ["node", "a b/c.js"]);
});

test("an unterminated quote is rejected instead of guessed", () => {
  assert.throws(() => splitCommand('node "unfinished'), /unterminated/);
});

test("an empty command yields no arguments", () => {
  assert.deepEqual(splitCommand("   "), []);
});

test("shell metacharacters are passed as arguments, not executed", async () => {
  const marker = path.join(os.tmpdir(), `wf-bridge-${process.pid}-${Date.now()}`);
  const backend = new BridgeBackend(
    `"${process.execPath}" "${FAKE}" && echo pwned > "${marker}"`,
    { timeout: 5000 },
  );
  try {
    await backend.capabilities();
  } finally {
    await backend.close();
  }
  assert.equal(fs.existsSync(marker), false, "the second command must not run");
  if (fs.existsSync(marker)) fs.rmSync(marker, { force: true });
});
