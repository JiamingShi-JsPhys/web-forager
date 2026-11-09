"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto } = require("../lib/safety");
const { extractVideoMeta, findDanmaku, bvidFrom, hasLoginWall } = require("../lib/snapshot");
const { BILIBILI } = require("../lib/selectors");
const { markVisited } = require("../lib/session");

const NAME = "bili-danmaku";

module.exports = {
  name: NAME,
  description: "Capture visible danmaku for one Bilibili video, preferring bridge observation over DOM scraping (experimental).",
  requires: ["url"],

  async run(ctx) {
    let url = ctx.options.url;
    if (!url && ctx.options.bvid) url = `${BILIBILI.homeUrl}video/${ctx.options.bvid}`;
    if (!url) throw new ActorError("argument", "bili-danmaku needs --url or --bvid");

    await guardedGoto(ctx, url);
    markVisited(ctx.session, url);

    const snapshot = await ctx.backend.snapshot();
    if (hasLoginWall(snapshot) && !extractVideoMeta(snapshot).bvid) {
      throw new ActorError(
        "login_required",
        "Bilibili asked for credentials before the player loaded",
        "Use a logged-in extension bridge; web-forager never supplies credentials itself.",
      );
    }

    const meta = extractVideoMeta(snapshot);
    let entries = [];
    let source = "network";
    let warnings = [];

    // Observation comes first: a bridge that watches the player sees the real
    // stream regardless of how the page draws it. DOM text is a fallback that
    // assumes one visible "mm:ss text" layout, so it is labelled as such.
    const capabilities = await ctx.backend.capabilities();
    if (capabilities.observe && typeof ctx.backend.observe === "function") {
      try {
        const observed = await ctx.backend.observe("danmaku", Number(ctx.options.observeMs || 3000));
        entries = ((observed && (observed.entries || observed.events)) || []).map((entry) => ({
          time: entry.time || entry.timestamp || "",
          text: String(entry.text || entry.content || "").slice(0, 200),
        }));
      } catch (error) {
        ctx.warn(`network observation unavailable: ${error.message}`);
      }
    } else {
      ctx.warn("the bridge did not declare observe; falling back to DOM text extraction");
    }

    if (!entries.length) {
      entries = findDanmaku(snapshot);
      source = "dom";
      if (entries.length) {
        warnings.push(
          "danmaku came from DOM text, which assumes one visible 'mm:ss text' layout; treat the list as partial",
        );
      }
    }

    if (!entries.length) ctx.warn("no danmaku found in the observation window or the DOM snapshot");

    ctx.capture({
      playbook: NAME,
      url: meta.url || url,
      metadata: {
        bvid: meta.bvid || bvidFrom(url),
        title: meta.title,
        site: "bilibili",
        source,
        experimental: true,
        count: entries.length,
      },
      markdown: entries.length
        ? entries.map((entry) => `- ${entry.time || ""} ${entry.text}`.trim()).join("\n")
        : "No danmaku captured.",
      tables: [
        {
          name: "danmaku",
          columns: ["time", "text"],
          rows: entries.map((entry) => [entry.time || "", entry.text || ""]),
        },
      ],
      warnings,
    });

    return {
      summary: {
        captured: 1,
        danmaku: entries.length,
        source,
        experimental: true,
        status: entries.length ? "ok" : "degraded",
      },
    };
  },
};
