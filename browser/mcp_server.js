#!/usr/bin/env node
"use strict";

const path = require("node:path");
const { spawn } = require("node:child_process");
const { version } = require("./package.json");
const { listPlaybooks } = require("./lib/playbooks");
const { loadSession, sessionPath } = require("./lib/session");
const { BACKENDS } = require("./lib/backend");
const { doctorReport } = require("./lib/doctor");

const SERVER_INFO = { name: "web-forager-browser", version };
const DEFAULT_PROTOCOL = "2024-11-05";
const RUN_TIMEOUT_MS = 300000;

const TOOLS = [
  {
    name: "browser_list",
    description: "List the read-only web-forager-browser playbooks and the supported browser backends.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "browser_run",
    description:
      "Run one read-only playbook in a real browser through the configured bridge. Returns the same record shape the CLI writes. Write-like actions stay denied unless allowWrite is explicitly true.",
    inputSchema: {
      type: "object",
      properties: {
        playbook: {
          type: "string",
          enum: ["bili-feed", "bili-video", "bili-chain", "bili-danmaku", "zhihu-dig", "xhs-dig", "search-dig"],
          description: "Playbook to run.",
        },
        url: { type: "string", description: "Seed or target URL." },
        bvid: { type: "string", description: "Bilibili video id (BV...)." },
        query: { type: "string", description: "Search query for *-dig playbooks." },
        session: { type: "string", description: "Resumable session name. Defaults to default." },
        maxItems: { type: "integer", minimum: 1, maximum: 100 },
        maxScreens: { type: "integer", minimum: 1, maximum: 50 },
        commentScrolls: { type: "integer", minimum: 0, maximum: 50 },
        observeMs: { type: "integer", minimum: 0, maximum: 60000 },
        minInterval: { type: "integer", minimum: 0 },
        root: { type: "string", description: "Four-zone workspace root; writes process/web-forager/browser/ and _broadcast/." },
        out: { type: "string", description: "Write the full JSON result to this file." },
        bridge: { type: "string", description: "Bridge command. Defaults to the bundled playwright bridge, then WEB_FORAGER_BRIDGE." },
        backend: { type: "string", enum: Object.keys(BACKENDS), description: "Backend label: iab, extension or cdp." },
        dryRun: { type: "boolean", description: "Print the plan without opening a browser." },
        allowWrite: {
          type: "boolean",
          description: "Permit write-like clicks. Only set after the user explicitly authorises one action.",
        },
        strictRobots: {
          type: "boolean",
          description: "Consult robots.txt before every navigation and refuse disallowed pages (default false).",
        },
        core: {
          type: "boolean",
          description: "Report records in the shared core-1 schema instead of the full browser record.",
        },
      },
      required: ["playbook"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_session",
    description: "Read a resumable session: captured ids, visited pages and the followed chain.",
    inputSchema: {
      type: "object",
      properties: {
        session: { type: "string", description: "Session name. Defaults to default." },
      },
      additionalProperties: false,
    },
  },
  {
    name: "browser_doctor",
    description:
      "Check the browser stack without opening a page: Node, the bridge command, the playwright package, the Chromium binary, the profile directory and hints for whatever is missing.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
];

function textResult(value, isError = false) {
  return {
    content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }],
    isError,
  };
}

function runPlaybook(args) {
  return new Promise((resolve) => {
    const argv = [path.join(__dirname, "run.js"), "--agent", "--playbook", String(args.playbook)];
    const textual = [
      "url",
      "bvid",
      "query",
      "session",
      "maxItems",
      "maxScreens",
      "commentScrolls",
      "observeMs",
      "minInterval",
      "root",
      "out",
      "bridge",
      "backend",
    ];
    for (const key of textual) {
      if (args[key] === undefined || args[key] === null || args[key] === "") continue;
      const flag = key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
      argv.push(`--${flag}`, String(args[key]));
    }
    if (args.dryRun) argv.push("--dry-run");
    if (args.allowWrite === true) argv.push("--allow-write");
    if (args.strictRobots === true) argv.push("--strict-robots");
    if (args.core === true) argv.push("--core");

    const child = spawn(process.execPath, argv, { cwd: __dirname, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve(textResult({ ok: false, error: { code: "timeout", message: "playbook run timed out" } }, true));
    }, RUN_TIMEOUT_MS);
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      const line = stdout
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean)
        .pop();
      let payload;
      try {
        payload = line ? JSON.parse(line) : null;
      } catch {
        payload = null;
      }
      if (!payload) {
        resolve(textResult({ ok: false, error: { code: "protocol", message: stderr || "no JSON envelope" } }, true));
        return;
      }
      const isError = payload.ok === false || code !== 0;
      resolve(textResult(payload, isError));
    });
  });
}

function sessionSummary(args) {
  const name = args.session || "default";
  const session = loadSession(name);
  return {
    name: session.name,
    file: sessionPath(name),
    playbook: session.playbook,
    created_at: session.created_at,
    updated_at: session.updated_at,
    captured: session.captured,
    visited: session.visited,
    chain: session.chain,
  };
}

async function callTool(name, args = {}) {
  if (name === "browser_list") {
    return textResult({ playbooks: listPlaybooks(), backends: BACKENDS });
  }
  if (name === "browser_run") {
    if (!args.playbook) return textResult({ ok: false, error: { code: "argument", message: "playbook is required" } }, true);
    return runPlaybook(args);
  }
  if (name === "browser_session") {
    try {
      return textResult(sessionSummary(args));
    } catch (error) {
      return textResult({ ok: false, error: { code: "argument", message: error.message } }, true);
    }
  }
  if (name === "browser_doctor") {
    const report = doctorReport();
    return textResult({ ok: report.ok, data: report });
  }
  return textResult({ ok: false, error: { code: "unknown_tool", message: `unknown tool: ${name}` } }, true);
}

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

async function handle(message) {
  const { id, method, params } = message;
  const isRequest = id !== undefined && id !== null;
  try {
    if (method === "initialize") {
      send({
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: (params && params.protocolVersion) || DEFAULT_PROTOCOL,
          capabilities: { tools: { listChanged: false } },
          serverInfo: SERVER_INFO,
          instructions:
            "web-forager-browser drives a real browser read-only. Use browser_list before browser_run and browser_session to resume without repeating captures; browser_doctor names what is missing when the first run fails.",
        },
      });
      return;
    }
    if (method === "notifications/initialized" || method === "initialized") return;
    if (method === "ping") {
      if (isRequest) send({ jsonrpc: "2.0", id, result: {} });
      return;
    }
    if (method === "tools/list") {
      send({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
      return;
    }
    if (method === "tools/call") {
      const name = params && params.name;
      const args = (params && params.arguments) || {};
      const result = await callTool(name, args);
      send({ jsonrpc: "2.0", id, result });
      return;
    }
    if (isRequest) {
      send({ jsonrpc: "2.0", id, error: { code: -32601, message: `method not found: ${method}` } });
    }
  } catch (error) {
    if (isRequest) send({ jsonrpc: "2.0", id, error: { code: -32603, message: error.message } });
  }
}

function main() {
  let buffer = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    buffer += chunk;
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) {
        let message;
        try {
          message = JSON.parse(line);
        } catch {
          send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } });
          message = null;
        }
        if (message) handle(message);
      }
      newline = buffer.indexOf("\n");
    }
  });
}

if (require.main === module) main();

module.exports = { TOOLS, callTool, handle, sessionSummary };
