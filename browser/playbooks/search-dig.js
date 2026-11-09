"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto } = require("../lib/safety");
const { findVideoCards, rankByQuery, diagnoseEmpty } = require("../lib/snapshot");
const { BILIBILI } = require("../lib/selectors");
const { searchVideos } = require("../lib/bili-api");
const { hasCaptured, markCaptured, markVisited } = require("../lib/session");
const { openAndCapture, snapshotSafe } = require("./shared");

const NAME = "search-dig";

module.exports = {
  name: NAME,
  description: "Search Bilibili, rank the result cards by query overlap, and capture the best unseen result.",
  requires: ["query"],

  async run(ctx) {
    const query = ctx.options.query;
    if (!query) throw new ActorError("argument", "search-dig needs --query");

    const base = ctx.options.url || BILIBILI.searchUrl;
    const searchUrl = `${base}?keyword=${encodeURIComponent(query)}`;

    // The search JSON is stable where the result page's markup is not, so ask
    // it first and fall back to the page only when it cannot answer.
    let ranked = [];
    let source = "page";
    try {
      const cards = await searchVideos(query, 20);
      if (cards.length) {
        ranked = rankByQuery(cards, query);
        source = "api";
      }
    } catch (error) {
      if (String(error.message) !== "disabled") {
        ctx.warn(`bilibili search API unavailable (${error.message}); reading the result page instead`);
      }
    }

    if (source === "page") {
      await guardedGoto(ctx, searchUrl);
      markVisited(ctx.session, searchUrl);
      const snapshot = await snapshotSafe(ctx, "the search page");
      ranked = rankByQuery(findVideoCards(snapshot), query);
      if (!ranked.length) {
        const reason = diagnoseEmpty(snapshot);
        if (reason === "blocked") {
          throw new ActorError(
            "blocked",
            "Bilibili search returned an anti-bot or error page instead of result cards",
            "Wait and retry later. web-forager does not solve challenges.",
          );
        }
        ctx.warn(`degraded: no result cards found (${reason})`);
        return { summary: { query, results: 0, captured: 0, status: "degraded", reason } };
      }
    }

    ctx.capture({
      playbook: NAME,
      url: searchUrl,
      metadata: { query, results: ranked.length, source },
      markdown: ranked
        .slice(0, 10)
        .map((card, index) => `${index + 1}. ${card.title} - ${card.url}`)
        .join("\n"),
      tables: [
        {
          name: "search results",
          columns: ["#", "title", "bvid", "url"],
          rows: ranked.slice(0, 20).map((card, index) => [index + 1, card.title, card.bvid, card.url]),
        },
      ],
    });

    const target = ranked.find((card) => !hasCaptured(ctx.session, card.bvid));
    if (!target) {
      return { summary: { query, results: ranked.length, captured: 0, status: "ok", reason: "all-captured" }, warnings: ["all results already captured"] };
    }

    const result = await openAndCapture(ctx, target.url, {
      commentScrolls: Number(ctx.options.commentScrolls === undefined ? 1 : ctx.options.commentScrolls),
      playbook: NAME,
    });
    markCaptured(ctx.session, {
      id: target.bvid,
      url: target.url,
      title: target.title,
      playbook: NAME,
    });

    return {
      summary: {
        query,
        results: ranked.length,
        captured: 1,
        opened: result.meta.bvid || target.bvid,
        title: result.meta.title || target.title,
        status: "ok",
        source,
      },
    };
  },
};
