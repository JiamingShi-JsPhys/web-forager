"use strict";

const { guardedGoto, guardedScroll } = require("../lib/safety");
const { extractVideoMeta, commentCandidates, pageTitle, bodyText } = require("../lib/snapshot");
const { markCaptured, markVisited } = require("../lib/session");

function videoMarkdown(meta, comments) {
  const lines = [`# ${meta.title}`, ""];
  if (meta.bvid) lines.push(`- BV: ${meta.bvid}`);
  if (meta.url) lines.push(`- URL: ${meta.url}`);
  for (const [key, value] of Object.entries(meta.stats || {})) lines.push(`- ${key}: ${value}`);
  if (comments.length) {
    lines.push("", "## Visible comments", "");
    for (const comment of comments) lines.push(`- ${comment}`);
  }
  return lines.join("\n");
}

async function captureCurrent(ctx, options = {}) {
  const scrolls = Number(options.commentScrolls === undefined ? 3 : options.commentScrolls);
  let snapshot = await ctx.backend.snapshot();
  const meta = extractVideoMeta(snapshot);
  const comments = [];
  const seen = new Set();
  for (let index = 0; index <= scrolls; index += 1) {
    for (const comment of commentCandidates(snapshot)) {
      if (!seen.has(comment)) {
        seen.add(comment);
        comments.push(comment);
      }
    }
    if (index < scrolls) {
      await guardedScroll(ctx, 700);
      snapshot = await ctx.backend.snapshot();
    }
  }

  const record = ctx.capture({
    playbook: options.playbook || "bili-video",
    url: meta.url || (snapshot && snapshot.url) || "",
    metadata: { bvid: meta.bvid, title: meta.title, stats: meta.stats },
    markdown: videoMarkdown(meta, comments),
    warnings: meta.bvid ? [] : ["no BV id found on the page"],
  });
  if (meta.bvid) markCaptured(ctx.session, { id: meta.bvid, url: meta.url, title: meta.title, playbook: options.playbook });

  return { record, meta, snapshot, comments };
}

async function openAndCapture(ctx, url, options = {}) {
  await guardedGoto(ctx, url);
  markVisited(ctx.session, url);
  return captureCurrent(ctx, options);
}

async function capturePage(ctx, options = {}) {
  const snapshot = await ctx.backend.snapshot();
  const title = pageTitle(snapshot) || options.url || "page";
  const body = bodyText(snapshot);
  const record = ctx.capture({
    playbook: options.playbook || "page",
    url: (snapshot && snapshot.url) || options.url || "",
    metadata: { site: options.site || "", title },
    markdown: body || "(no readable text extracted from the snapshot)",
    warnings: body ? [] : ["no readable text extracted from the snapshot"],
  });
  markCaptured(ctx.session, {
    id: options.url || (snapshot && snapshot.url) || title,
    url: options.url || (snapshot && snapshot.url) || "",
    title,
    playbook: options.playbook,
  });
  return { record, snapshot, title, body };
}

module.exports = { captureCurrent, openAndCapture, capturePage, videoMarkdown };
