#!/usr/bin/env node
"use strict";

// A bridge from before the `describe` handshake existed: it answers the page
// methods but reports "unknown method" for anything else. web-forager-browser
// must fall back to conservative capabilities instead of assuming them.

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let newline = buffer.indexOf("\n");
  while (newline >= 0) {
    const line = buffer.slice(0, newline).trim();
    buffer = buffer.slice(newline + 1);
    newline = buffer.indexOf("\n");
    if (!line) continue;
    const message = JSON.parse(line);
    const send = (payload) => process.stdout.write(`${JSON.stringify(payload)}\n`);
    if (message.method === "goto") {
      send({ jsonrpc: "2.0", id: message.id, result: { url: message.params.url } });
    } else if (message.method === "snapshot") {
      send({ jsonrpc: "2.0", id: message.id, result: { url: "", title: "legacy", nodes: [] } });
    } else {
      send({ jsonrpc: "2.0", id: message.id, error: { code: "protocol", message: `unknown method: ${message.method}` } });
    }
  }
});
