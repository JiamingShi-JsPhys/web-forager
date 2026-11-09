"use strict";

const { nowIso } = require("./session");

function makeRecord(fields) {
  return {
    schema_version: "2",
    source: "web-forager-browser",
    mode: "browser",
    playbook: fields.playbook || "",
    url: fields.url || "",
    captured_at: nowIso(),
    backend: fields.backend || "unknown",
    metadata: fields.metadata || {},
    markdown: fields.markdown || "",
    tables: Array.isArray(fields.tables) ? fields.tables : [],
    warnings: Array.isArray(fields.warnings) ? fields.warnings : [],
    compliance: fields.compliance || { strict_robots: false, robots_checked: false, checks: [] },
    viewport_evidence: fields.viewport_evidence || null,
    interaction_trace: Array.isArray(fields.interaction_trace) ? fields.interaction_trace : [],
  };
}

// Fold a browser record and an HTTP record onto the same core, so a caller can
// read one list without branching on the mode. Everything the two modes do not
// share is preserved under `extra` rather than dropped.
function normalizeRecord(record) {
  const value = record || {};
  const metadata = value.metadata || {};
  const browser = value.source === "web-forager-browser" || Boolean(value.captured_at);
  const collectedAt = value.collected_at || (browser ? value.captured_at : value.fetched_at) || "";
  const url = value.url || value.final_url || "";
  const title = value.title || metadata.title || "";
  const shared = [
    "metadata",
    "markdown",
    "tables",
    "warnings",
    "url",
    "final_url",
    "title",
    "captured_at",
    "fetched_at",
    "collected_at",
    "source",
    "mode",
    "schema_version",
  ];
  const extra = {};
  for (const [key, item] of Object.entries(value)) {
    if (!shared.includes(key)) extra[key] = item;
  }
  if (value.source && value.source !== "web-forager" && value.source !== "web-forager-browser") {
    extra.record_source = value.source;
  }
  return {
    schema_version: "core-1",
    source: browser ? "web-forager-browser" : "web-forager",
    mode: browser ? "browser" : "http",
    url,
    title,
    collected_at: collectedAt,
    metadata,
    markdown: value.markdown || "",
    tables: Array.isArray(value.tables) ? value.tables : [],
    warnings: Array.isArray(value.warnings) ? value.warnings : [],
    extra,
  };
}

function slugify(text, fallback = "capture") {
  const value = String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9一-鿿]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return value || fallback;
}

function recordToMarkdown(record) {
  const title = record.metadata.title || record.metadata.bvid || record.url || "capture";
  const lines = [`# ${title}`, ""];
  if (record.url) lines.push(`Source: ${record.url}`);
  lines.push(`Playbook: ${record.playbook} | Backend: ${record.backend} | Captured: ${record.captured_at}`);
  const meta = record.metadata || {};
  const scalar = Object.entries(meta).filter(([, value]) => value !== null && value !== undefined && typeof value !== "object");
  if (scalar.length) {
    lines.push("", "## Metadata", "");
    for (const [key, value] of scalar) lines.push(`- ${key}: ${value}`);
  }
  if (record.markdown) lines.push("", "## Capture", "", record.markdown.trim());
  if (record.tables && record.tables.length) {
    lines.push("", "## Tables", "");
    for (const table of record.tables) {
      lines.push(`### ${table.name || "table"}`, "");
      lines.push(`| ${table.columns.join(" | ")} |`);
      lines.push(`| ${table.columns.map(() => "---").join(" | ")} |`);
      for (const row of table.rows) lines.push(`| ${row.join(" | ")} |`);
      lines.push("");
    }
  }
  if (record.warnings && record.warnings.length) {
    lines.push("", "## Warnings", "");
    for (const warning of record.warnings) lines.push(`- ${warning}`);
  }
  return `${lines.join("\n").trim()}\n`;
}

module.exports = { makeRecord, normalizeRecord, recordToMarkdown, slugify };
