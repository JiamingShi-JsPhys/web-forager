---
name: scholar
description: Query arXiv, Crossref or PubMed, or resolve a DOI into a normalised bibliographic record.
metadata:
  skill: web-forager
  stage: domain_extensions
---

# /scholar — find papers through public APIs

Use this when the task is **literature discovery**. These are documented query
APIs, not scraped result pages, so the output is stable and polite.

## Usage

```bash
python run.py --action scholar --source arxiv --query "<TOPIC>" --num-results 10
python run.py --action scholar --source arxiv --query "<PAPER TITLE>" --field ti
python run.py --action scholar --source crossref --query "<TOPIC>"
python run.py --action scholar --source pubmed --query "<TOPIC>" --num-results 5
python run.py --action scholar --source doi --query "10.1038/nature14539"
```

Each record carries `title, authors, published, journal, volume, issue, pages,
doi, url, pdf_url, abstract, type, keywords`. `published` and `updated` are
`YYYY[-MM[-DD]]`; a Crossref search drops component rows, and an unregistered
DOI exits 2 with `not_found`. Use `--sort
relevance|submittedDate|lastUpdatedDate` and `--field all|ti|au|abs` for arXiv.

The tool returns metadata and abstracts only; it does not download or
redistribute full papers.
