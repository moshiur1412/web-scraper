# Program scraper (light + modular)

Reads `urls.txt` + `prompt`, scrapes each page (JSON-LD -> embedded state JSON -> HTML),
and writes pretty `programs.json`.

## Run

```
python -m venv .venv
.venv\Scripts\activate        # Windows (bash: source .venv/bin/activate)
pip install -r requirements.txt
python scrape.py --input urls.txt --out programs.json --delay 3
```

Resume is automatic: re-run the same command and already-scraped URLs are skipped
(`programs.jsonl` is the resume log, `errors.jsonl` holds rejected records).
Use `--fresh` to start over (deletes those logs).

### Pagination

Listing pages are followed automatically through their *next* link
(`rel="next"` or `<a name="next">`, same host only), and every page is folded
into one record (listings are deduped by URL). Controls:

- `--no-next` -- do not follow pagination
- `--next-limit 20` -- max pages per input URL
- `input_format.FOLLOW_NEXT_PAGES` / `MAX_PAGES_PER_URL` -- defaults

### Sites that block bots

`fetcher.py` sends a full browser header set (`sec-ch-ua`, `sec-fetch-*`,
`Priority`, ...). Mastersportal/Cloudflare returns **403 without those headers**
and 200 with them. On 401/403/429 the domain is stopped (never bypassed),
logged, and the run finishes cleanly with whatever was collected.

## Where to change things (this is the "separate formats" part)

| You want to change...            | Edit |
|----------------------------------|------|
| Input files, comments, dedupe    | `input_format.py` (`URLS_FILE`, `PROMPT_FILE`, `COMMENT_PREFIXES`, ...) |
| Output fields / JSON schema      | `output_format.py` (`SCHEMA`, `REQUIRED_FIELDS`) |
| Output file names, indent, meta  | `output_format.py` (`OUT_JSON`, `OUT_JSONL`, `WRAP_WITH_META`, ...) |
| Politeness (delay, UA, robots)   | `fetcher.py` (top constants) |
| Extraction rules / new site      | `parsers.py` (`PARSERS` registry) |

Nothing else hard-codes input or output details.

## Add a new site parser

1. In `parsers.py`, subclass `BaseParser`:

```python
class MySiteParser(BaseParser):
    domains = ("example.ac.uk",)   # match on hostname
    source = "example"
    def fill(self, record, soup, jsonld, embedded, html, url):
        super().fill(record, soup, jsonld, embedded, html, url)
        # only set fields the generic pass could not find
        record["field_of_study"] = ...
```

2. Append it to `PARSERS` (before `Generic` behaviour matters only by order; first match wins).
3. Re-run `python scrape.py`.

## Output

`WRAP_WITH_META = True` (default) writes `{"meta": {...prompt, counts...}, "programs": [...]}`.
Set it to `False` in `output_format.py` for a bare JSON array of records.
Missing values are always `null` (or `[]` for lists) -- nothing is ever guessed.

Two field groups exist so every page type maps accurately:

- **program pages** -- fill `program_name`, `university`, `duration`, `tuition_fee`, ...
- **listing/search pages** (JSON-LD `SearchResultsPage`/`ItemList`) -- program fields
  stay `null` (they don't exist there); the page's entity list goes into `listings`:
  `[{"name", "url", "description", "rating": {"value","count","best","worst"}}]`
  and `page_title` holds the raw page title.

Add/remove fields only in `SCHEMA` (`output_format.py`); validation follows it automatically.
