"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto } = require("../lib/safety");
const { findLinks, rankByQuery, diagnoseEmpty } = require("../lib/snapshot");
const { XIAOHONGSHU } = require("../lib/selectors");
const { hasCaptured, markCaptured, markVisited } = require("../lib/session");
const { capturePage, snapshotSafe } = require("./shared");

const NAME = "xhs-dig";
const SEARCH = XIAOHONGSHU.searchUrl;
const RESULT_LINK = XIAOHONGSHU.resultLink;

module.exports = {
  name: NAME,
  description: "Search Xiaohongshu public notes, rank note links by query overlap, and capture the best unseen note.",
  requires: ["query"],

  async run(ctx) {
    const query = ctx.options.query;
    if (!query) throw new ActorError("argument", "xhs-dig needs --query");

    const searchUrl = `${SEARCH}${encodeURIComponent(query)}`;
    await guardedGoto(ctx, searchUrl);
    markVisited(ctx.session, searchUrl);

    const snapshot = await snapshotSafe(ctx, "the search page");
    const ranked = rankByQuery(findLinks(snapshot, RESULT_LINK), query);
    if (!ranked.length) {
      const reason = diagnoseEmpty(snapshot);
      if (reason === "login") {
        throw new ActorError(
          "login_required",
          "Xiaohongshu showed a login wall before any note links",
          "Use a logged-in extension bridge, or open a public note URL directly with the page playbook.",
        );
      }
      if (reason === "blocked") {
        throw new ActorError(
          "blocked",
          "Xiaohongshu returned an anti-bot or error page instead of notes",
          "Wait and retry later, or reuse a logged-in profile through the extension backend. web-forager does not solve challenges.",
        );
      }
      ctx.warn(`degraded: no note links found (${reason})`);
      return { summary: { query, notes: 0, captured: 0, status: "degraded", reason } };
    }

    ctx.capture({
      playbook: NAME,
      url: searchUrl,
      metadata: { query, site: "xiaohongshu", notes: ranked.length },
      markdown: ranked
        .slice(0, 10)
        .map((item, index) => `${index + 1}. ${item.title} - ${item.url}`)
        .join("\n"),
      tables: [
        {
          name: "xiaohongshu notes",
          columns: ["#", "title", "url"],
          rows: ranked.slice(0, 20).map((item, index) => [index + 1, item.title, item.url]),
        },
      ],
    });

    const target = ranked.find((item) => !hasCaptured(ctx.session, item.url));
    if (!target) {
      ctx.warn("all notes already captured");
      return { summary: { query, notes: ranked.length, captured: 0, status: "ok", reason: "all-captured" } };
    }

    await guardedGoto(ctx, target.url);
    markVisited(ctx.session, target.url);
    const page = await capturePage(ctx, { url: target.url, site: "xiaohongshu", playbook: NAME });
    markCaptured(ctx.session, { id: target.url, url: target.url, title: page.title, playbook: NAME });

    return {
      summary: {
        query,
        notes: ranked.length,
        captured: 1,
        opened: target.url,
        title: page.title,
        status: page.status,
        reason: page.reason || "",
      },
    };
  },
};
