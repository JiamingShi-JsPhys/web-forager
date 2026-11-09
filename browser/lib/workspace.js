"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { recordToMarkdown, slugify } = require("./record");

function stamp(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  );
}

function writeRecords(records, root) {
  if (!root) return null;
  const processDir = path.join(root, "process", "web-forager", "browser");
  const broadcastDir = path.join(root, "_broadcast");
  fs.mkdirSync(processDir, { recursive: true });
  fs.mkdirSync(broadcastDir, { recursive: true });

  const at = stamp();
  const files = [];
  records.forEach((record, index) => {
    const slug = slugify(record.metadata.title || record.metadata.bvid || `capture-${index + 1}`);
    const base = `web-forager-browser_${at}_${slug}`;
    const jsonFile = path.join(processDir, `${base}.json`);
    const mdFile = path.join(processDir, `${base}.md`);
    const broadcastFile = path.join(broadcastDir, `${base}.json`);
    const body = `${JSON.stringify(record, null, 2)}\n`;
    fs.writeFileSync(jsonFile, body, "utf8");
    fs.writeFileSync(mdFile, recordToMarkdown(record), "utf8");
    fs.writeFileSync(broadcastFile, body, "utf8");
    files.push({ json: jsonFile, markdown: mdFile, broadcast: broadcastFile });
  });

  return { process_dir: processDir, broadcast_dir: broadcastDir, files };
}

module.exports = { writeRecords, stamp };
