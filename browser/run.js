#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const { version } = require("./package.json");
const { createBackend, BACKENDS } = require("./lib/backend");
const { getPlaybook, listPlaybooks } = require("./lib/playbooks");
const { loadSession, saveSession, sessionPath } = require("./lib/session");
const { makeRecord } = require("./lib/record");
const { writeRecords } = require("./lib/workspace");
const { makeContext } = require("./lib/context");
const { ActorError, asActorError } = require("./lib/errors");

const EXIT = {
  argument: 2,
  backend_unavailable: 3,
  navigation: 4,
  capture: 5,
  login_required: 6,
  confirmation_required: 7,
  unexpected: 1,
};

const BOOLEAN_FLAGS = new Set(["list", "dry-run", "agent", "allow-write", "help", "version"]);

function camel(name) {
  return name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

function parse(argv) {
  const options = {
    session: "default",
    backend: "iab",
    minInterval: 1000,
    maxItems: 10,
    maxScreens: 3,
    commentScrolls: 3,
    observeMs: 3000,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new ActorError("argument", `unexpected argument: ${token}`);
    const equals = token.indexOf("=");
    let key;
    let value;
    if (equals >= 0) {
      key = token.slice(2, equals);
      value = token.slice(equals + 1);
    } else {
      key = token.slice(2);
      if (BOOLEAN_FLAGS.has(key)) {
        value = true;
      } else {
        value = argv[index + 1];
        if (value === undefined) throw new ActorError("argument", `missing value for --${key}`);
        index += 1;
      }
    }
    options[camel(key)] = value;
  }
  return options;
}

function printHelp() {
  process.stdout.write(
    [
      "web-forager-browser " + version,
      "",
      "Usage: node run.js --playbook <name> [options]",
      "",
      "Playbooks:",
      ...listPlaybooks().map((item) => `  ${item.name.padEnd(12)} ${item.description}`),
      "",
      "Options:",
      "  --session NAME       resumable session name (default: default)",
      "  --url URL            seed or target URL",
      "  --bvid BV...         Bilibili video id",
      "  --query TEXT         search query (search-dig)",
      "  --max-items N        maximum captured items (default: 10)",
      "  --max-screens N      feed screens to scroll (default: 3)",
      "  --comment-scrolls N  comment scrolls per video (default: 3)",
      "  --observe-ms N       danmaku observation window in ms (default: 3000)",
      "  --min-interval MS    minimum delay between actions (default: 1000)",
      "  --root DIR           write into a four-zone workspace",
      "  --out FILE           write the full result as JSON",
      "  --bridge CMD         browser bridge command (or WEB_FORAGER_BRIDGE)",
      "  --backend NAME       iab, extension or cdp (default: iab)",
      "  --allow-write        permit write-like clicks (default: deny)",
      "  --dry-run            print the plan without opening a browser",
      "  --agent              emit a {\"ok\":...} JSON envelope",
      "  --list               list playbooks",
      "  --version            print the version",
    ].join("\n") + "\n",
  );
}

function emit(payload, options, humanLines) {
  if (options.agent) {
    process.stdout.write(`${JSON.stringify({ ok: true, data: payload })}\n`);
    return;
  }
  for (const line of humanLines) process.stdout.write(`${line}\n`);
  if (!options.root && !options.out) {
    process.stdout.write(`${JSON.stringify(payload.records, null, 2)}\n`);
  }
}

async function main() {
  let options = { agent: false };
  try {
    options = { ...options, ...parse(process.argv.slice(2)) };
  } catch (error) {
    return fail(error, options.agent);
  }

  if (options.help) {
    printHelp();
    return 0;
  }
  if (options.version) {
    process.stdout.write(`web-forager-browser ${version}\n`);
    return 0;
  }
  if (options.list) {
    const items = listPlaybooks();
    if (options.agent) process.stdout.write(`${JSON.stringify({ ok: true, data: items })}\n`);
    else for (const item of items) process.stdout.write(`${item.name}: ${item.description}\n`);
    if (!options.agent) process.stdout.write(`backends: ${Object.keys(BACKENDS).join(", ")}\n`);
    return 0;
  }

  if (!options.playbook) return fail(new ActorError("argument", "--playbook is required"), options.agent);

  let playbook;
  try {
    playbook = getPlaybook(options.playbook);
  } catch (error) {
    return fail(new ActorError("argument", error.message), options.agent);
  }
  const session = loadSession(options.session, { playbook: playbook.name });
  const bridge = options.bridge || process.env.WEB_FORAGER_BRIDGE || "";

  if (!BACKENDS[options.backend]) {
    return fail(
      new ActorError("argument", `unknown backend: ${options.backend}`, `Use one of: ${Object.keys(BACKENDS).join(", ")}.`),
      options.agent,
    );
  }

  if (options.dryRun) {
    const payload = {
      playbook: playbook.name,
      description: playbook.description,
      requires: playbook.requires,
      session: { name: session.name, captured: session.captured.length, chain: session.chain },
      backend: bridge ? options.backend : "unavailable",
      backend_detail: { name: options.backend, description: BACKENDS[options.backend], bridge: bridge ? "configured" : "missing" },
      plan: [
        "open the seed page",
        "read a DOM snapshot",
        "capture unseen items",
        "scroll and repeat within the action budget",
      ],
    };
    if (options.agent) process.stdout.write(`${JSON.stringify({ ok: true, data: payload })}\n`);
    else process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
    return 0;
  }

  const backend = createBackend({ bridge, backend: options.backend });
  const ctx = makeContext({
    backend,
    session,
    options,
    makeRecord,
    log: (message) => process.stderr.write(`${message}\n`),
  });

  let result;
  try {
    result = await playbook.run(ctx);
  } catch (error) {
    return fail(error, options.agent);
  } finally {
    saveSession(session);
    await backend.close();
  }
  const summary = result && result.summary !== undefined ? result.summary : result;

  const outputs = writeRecords(ctx.records, options.root);
  const payload = {
    playbook: playbook.name,
    session: {
      name: session.name,
      file: sessionPath(session.name),
      captured: session.captured.length,
      chain: session.chain,
    },
    summary,
    backend: { name: backend.name, capabilities: backend.capabilities() },
    warnings: [...ctx.warnings, ...((result && result.warnings) || [])],
    records: ctx.records,
    outputs,
  };

  if (options.out) fs.writeFileSync(options.out, `${JSON.stringify(payload, null, 2)}\n`, "utf8");

  const human = [
    `playbook: ${playbook.name}`,
    `captured: ${ctx.records.length}`,
    `session: ${sessionPath(session.name)}`,
  ];
  if (outputs) human.push(`process: ${outputs.process_dir}`, `broadcast: ${outputs.broadcast_dir}`);
  if (options.out) human.push(`result: ${options.out}`);
  emit(payload, options, human);
  return 0;
}

function fail(error, agent) {
  const actorError = asActorError(error);
  if (agent) {
    process.stdout.write(
      `${JSON.stringify({
        ok: false,
        error: { code: actorError.code, message: actorError.message, hint: actorError.hint },
      })}\n`,
    );
  } else {
    process.stderr.write(
      `web-forager-browser: ${actorError.code}: ${actorError.message}` +
        `${actorError.hint ? `\nhint: ${actorError.hint}` : ""}\n`,
    );
  }
  return EXIT[actorError.code] || EXIT.unexpected;
}

process.on("SIGINT", () => process.exit(130));

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error) => {
    process.exitCode = fail(error, false);
  });
