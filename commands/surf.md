---
name: surf
description: Search or open a page, then follow ranked in-page links with a resumable session.
metadata:
  skill: web-forager
  stage: domain_extensions
---

# /surf — browse link by link like a person

Use this when the task is **exploration**, not a single page. `surf` searches
(or opens a seed URL), fetches results, then follows links already present in
each page. It never constructs guessed URLs, submits forms or runs page
JavaScript, and every hop is re-checked against robots.txt.

## Usage

```bash
python run.py --action surf --query "<KEYWORDS>" --depth 1 --max-pages 5 --session research-01 --agent
python run.py --action surf --url "<URL>" --depth 2 --follow all --max-pages 10
```

- `--follow same-site` (default) keeps the walk on one site; `all` crosses
  domains; `none` only fetches the seed.
- `--session NAME` stores visited URLs and the trail under
  `~/.web-forager/sessions/`; the next run skips them.
- robots-denied links are recorded as entries with `error` and do not abort
  the walk. `--delay` applies to every hop.
