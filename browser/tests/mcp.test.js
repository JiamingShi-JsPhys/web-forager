"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { spawn } = require("node:child_process");

const SERVER = path.join(__dirname, "..", "mcp_server.js");

class Client {
  constructor() {
    this.child = spawn(process.execPath, [SERVER], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, WEB_FORAGER_BROWSER_HOME: path.join(__dirname, ".tmp-mcp-home") },
    });
    this.buffer = "";
    this.nextId = 1;
    this.pending = new Map();
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk) => this.onData(chunk));
  }

  onData(chunk) {
    this.buffer += chunk;
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).trim();
      this.buffer = this.buffer.slice(newline + 1);
      newline = this.buffer.indexOf("\n");
      if (!line) continue;
      const message = JSON.parse(line);
      const pending = this.pending.get(message.id);
      if (!pending) continue;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      pending.resolve(message);
    }
  }

  request(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`timeout waiting for ${method}`));
      }, 10000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  notify(method, params = {}) {
    this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
  }

  close() {
    this.child.kill();
  }
}

test("the MCP server initializes, lists tools and answers calls", async () => {
  const client = new Client();
  try {
    const init = await client.request("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "test", version: "1" },
    });
    assert.equal(init.result.serverInfo.name, "web-forager-browser");
    assert.equal(init.result.protocolVersion, "2024-11-05");
    client.notify("notifications/initialized");

    const list = await client.request("tools/list");
    const names = list.result.tools.map((tool) => tool.name).sort();
    assert.deepEqual(names, ["browser_doctor", "browser_list", "browser_run", "browser_session"]);

    const playbooks = await client.request("tools/call", { name: "browser_list", arguments: {} });
    const payload = JSON.parse(playbooks.result.content[0].text);
    assert.deepEqual(
      payload.playbooks.map((item) => item.name).sort(),
      ["bili-chain", "bili-danmaku", "bili-feed", "bili-video", "search-dig", "xhs-dig", "zhihu-dig"],
    );
    assert.ok(payload.backends.extension);

    const plan = await client.request("tools/call", {
      name: "browser_run",
      arguments: { playbook: "bili-feed", dryRun: true, session: "mcp-check" },
    });
    const runPayload = JSON.parse(plan.result.content[0].text);
    assert.equal(runPayload.ok, true);
    assert.equal(runPayload.data.playbook, "bili-feed");

    const session = await client.request("tools/call", {
      name: "browser_session",
      arguments: { session: "mcp-check" },
    });
    const sessionPayload = JSON.parse(session.result.content[0].text);
    assert.equal(sessionPayload.name, "mcp-check");
    assert.ok(Array.isArray(sessionPayload.captured));

    const doctor = await client.request("tools/call", { name: "browser_doctor", arguments: {} });
    const doctorPayload = JSON.parse(doctor.result.content[0].text);
    assert.equal(typeof doctorPayload.ok, "boolean");
    assert.match(doctorPayload.data.node, /^v\d+/);
    assert.equal(typeof doctorPayload.data.bridge.exists, "boolean");
    assert.ok(Array.isArray(doctorPayload.data.hints));
  } finally {
    client.close();
  }
});

test("unknown tools and methods are reported, not crashed", async () => {
  const client = new Client();
  try {
    const unknown = await client.request("tools/call", { name: "actor_write", arguments: {} });
    assert.equal(unknown.result.isError, true);
    const missing = await client.request("does/not/exist");
    assert.equal(missing.error.code, -32601);
  } finally {
    client.close();
  }
});
