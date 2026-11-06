---
name: map
description: Discover a site's page URLs from robots.txt Sitemap lines, sitemap indexes and .xml.gz files.
metadata:
  skill: web-forager
  stage: domain_extensions
---

# /map — inventory a site before reading it

Use this when the task is **site coverage**: find what pages exist instead of
guessing URLs. Sitemaps are published for crawlers, so discovery reads them
directly; every page later opened is still checked against robots.txt.

## Usage

```bash
python run.py --action map --url "https://example.org" --limit 500 --agent
python run.py --action map --url "https://example.org/sitemap_index.xml"
```

Output: `urls` (with `lastmod/changefreq/priority`), `sitemaps_read`,
`sources`, `errors`, and `note`. A site with no sitemap returns `count: 0`
rather than an error; inspect `note` and `errors`.
