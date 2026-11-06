"use strict";

const { nowIso } = require("./session");

function makeRecord(fields) {
  return {
    schema_version: "1",
    source: "web-forager-browser",
    playbook: fields.playbook || "",
    url: fields.url || "",
    captured_at: nowIso(),
    backend: fields.backend || "unknown",
    metadata: fields.metadata || {},
    markdown: fields.markdown || "",
    tables: Array.isArray(fields.tables) ? fields.tables : [],
    warnings: Array.isArray(fields.warnings) ? fields.warnings : [],
    viewport_evidence: fields.viewport_evidence || null,
    interaction_trace: Array.isArray(fields.interaction_trace) ? fields.interaction_trace : [],
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

module.exports = { makeRecord, recordToMarkdown, slugify };
