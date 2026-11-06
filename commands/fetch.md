---
name: fetch
description: Fetch one URL or a keyword query into clean Markdown with metadata, tables and chunks.
metadata:
  skill: web-forager
  stage: domain_extensions
---

# /fetch — read the web into clean Markdown

Use this when the task is **one page or one keyword query**. It fetches through
the robots-aware engine, extracts the article body, metadata and tables, and
returns Markdown plus optional context chunks.

## Usage

```bash
python run.py --action fetch --url "<URL>" --chunk-size 4000 --agent
python run.py --action fetch --query "<KEYWORDS>" --num-results 8 --max-pages 3
python run.py --action fetch --query "<KEYWORDS>" --engine all
```

- `--render always` needs Playwright; without it the command exits 6 and prints
  the install hint instead of a traceback.
- `--cache --cache-ttl 3600` reuses polite GET responses.
- PDFs need `pypdf`; without it the command exits 7 with an install hint.
- Add `--root <WS>` to write into `<WS>/process/web-forager/` and
  `<WS>/_broadcast/`.
- Add `--agent` for a `{"ok":true,"data":...}` envelope.
