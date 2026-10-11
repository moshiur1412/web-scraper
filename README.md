# Program scraper (mastersportal -> structured JSON)

Reads a list of program page URLs, scrapes each page politely, and writes records in the
exact JSON shape below. Missing values are always `null` -- nothing is ever guessed.

**Pipeline:** `urls.txt` -> `fetcher.py` (robots + delay + browser headers) ->
`parsers.py` (JSON-LD -> embedded state JSON -> HTML) -> `output_format.py`
(schema + validation) -> `programs.jsonl` (resume log) -> `programs.json` (final).

## Quick start

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python scrape.py --input urls.txt --out programs.json --delay 3
```

Bash: `source .venv/bin/activate` instead. Re-running the same command resumes
automatically (already-scraped URLs are skipped via `programs.jsonl`).
Use `--fresh` to start over (deletes the resume/crawl-state logs).

### Test run (the 5-university sample)

`urls_test.txt` holds one program page from five different universities.
`--no-frontier` means *only* those URLs are fetched and the persistent crawl state
(`frontier.txt` / `expanded.txt`) is neither read nor written. `--bare` writes a
plain JSON array instead of the `{meta, programs}` wrapper.

```bat
python scrape.py --input urls_test.txt --out test_programs.json --jsonl test_programs.jsonl --no-frontier --bare --fresh
```

Result: `test_programs.json` -- University of Southampton, University of Surrey,
University of Bath, University of Glasgow, The University of Edinburgh.
The Southampton record was checked field-by-field against the reference data
(fee 26,200 GBP/year, IELTS 7 / PTE 76 / Duolingo 130, September 2027 intake,
official URL, 60 credits, ...).

## Full UK crawl (all 272 universities, every programme)

`urls.txt` seeds the crawl with the mastersportal UK university listing. The crawler
then walks three levels automatically:

1. **Universities** -- `/search/universities/master/united-kingdom` (paginated) -> 272 university pages.
2. **Catalogues** -- every university page links its *full* programme catalogue
   (`/search/master?oi=<id>`), which is paginated (20 per page; e.g. Southampton has
   402 programmes = 21 pages). The profile page itself only shows a ~85-programme sample.
3. **Programmes** -- every `/studies/...` page becomes one record.

Everything is discovered, queued and resumed across runs (`frontier.txt` /
`expanded.txt` / `programs.jsonl`). Realistic volume: **~80k-120k programme pages**
-- at `--delay 2` that is roughly 40k pages/day, so **3-5 days** of background runs.
Leave it going with the driver script (it stops by itself when nothing is left):

```bat
run_full.bat
```

which loops: crawl pass (max 6h) -> `scrape.py --stats` (exit code 0 = finished)
-> wait 10 min -> next pass. Restart the machine or the script whenever you like;
the next pass continues where the previous one stopped. Useful commands while it runs:

```bat
python scrape.py --stats --input urls.txt     # records, universities, URLs left
python scrape.py ... --limit 50               # only 50 new records this run (smoke test)
python scrape.py ... --max-runtime 3600       # stop this pass after an hour
```

Final output: `programs.json` grouped by university -- `{"meta": {...},
"universities": {"University of Southampton": [programmes...], ...}}`.
Use `--group-by none` for a flat array, `--indent 0` for a compact file
(the grouped file of ~100k records is large; the JSONL on disk is the source of truth).

Flags that exist for this crawl: `--programs-only` (university pages are crawled for
links but not stored -- no more all-null records), `--group-by university`,
`--indent N`, `--limit N`, `--max-runtime SECONDS`, `--stats`.

## CLI options

| Flag | Meaning |
|------|---------|
| `--input urls.txt` | URL list file (default: `input_format.URLS_FILE`) |
| `--out programs.json` | Final pretty-printed JSON (default: `output_format.OUT_JSON`) |
| `--jsonl programs.jsonl` | Resume log (default: `output_format.OUT_JSONL`) |
| `--delay 3` | Seconds between requests to the same domain (+ 0-1 s jitter) |
| `--timeout 30` | HTTP timeout in seconds |
| `--fresh` | Ignore the resume log and crawl state, scrape everything again |
| `--no-frontier` | Process only the input URLs; do not read/write `frontier.txt` / `expanded.txt` |
| `--bare` | Write a bare JSON array (no `meta` wrapper) |
| `--no-next` | Do not follow listing pagination (`rel="next"`) |
| `--next-limit 200` | Max pages per listing (default: `input_format.MAX_PAGES_PER_URL`) |
| `--programs-only` | Store program records only (university pages are crawled for links) |
| `--group-by university` | Group the output by university instead of a flat array |
| `--indent 0` | JSON indent spaces (`0` = compact) |
| `--limit 50` | Stop after N new records (smoke tests) |
| `--max-runtime 3600` | Stop this pass cleanly after N seconds |
| `--stats` | Print progress (records, universities, URLs left) and exit; exit code 0 = crawl finished |
| `--no-robots` | Skip `robots.txt` checks (discouraged) |
| `-v` | Debug logging |

## Output format

One JSON object per program; the field set is defined in one place
(`SCHEMA` in `output_format.py`) and validation follows it automatically.

```json
{
  "program_name": "English with SEND",
  "university": "University of Southampton",
  "program_url": "https://www.mastersportal.com/studies/488477/english-with-send.html",
  "official_program_url": "https://www.southampton.ac.uk/courses/english-with-send-masters-pgcert",
  "degree_type": "Postgraduate Certificate",
  "delivered": "On Campus",
  "field_of_study": "Teaching English as a Foreign Language",
  "duration": { "full_time": "12 months", "part_time": null },
  "start_date": ["September 2027"],
  "apply_date": ["Before July 2027"],
  "campus_location": "Southampton, United Kingdom",
  "language": {
    "taught_in": "English",
    "requirements": [
      { "test": "Duolingo English Test", "min_score": "130" },
      { "test": "PTE Academic", "min_score": "76" },
      { "test": "IELTS", "min_score": "7" }
    ]
  },
  "tuition_fee": {
    "international": { "amount": 26200, "currency": "GBP", "per": "year", "note": null },
    "domestic": { "amount": 9535, "currency": "GBP", "per": "year" }
  },
  "credits": 60,
  "academic_requirements": { "gpa": null, "notes": null },
  "living_costs": { "amount": "697 - 1093", "currency": "GBP", "per": "month" },
  "overview": "The English with SEND programme from University of Southampton ...",
  "scholarships_available": true,
  "source": "mastersportal",
  "scraped_at": "2026-10-11T04:48:44Z"
}
```

Rules:

- **Never guess.** Any value the page does not state stays `null` (lists stay `[]`,
  or `null` when `EMPTY_LIST_AS_NULL` is on).
- **Tuition is always the real fee.** Mastersportal may rewrite the displayed number
  into your local currency; the original amount/currency live in
  `data-original-amount` / `data-original_html` and those are recorded.
  `per` is `"year"`, `"month"`, or `"total"` (one payment for the whole programme).
- **Duration is normalised:** `1 year` -> `12 months`.
- **Dates are month+year:** `2027-09-22` -> `September 2027`, deadlines -> `Before July 2027`,
  an open application window stays `Anytime`.
- `WRAP_WITH_META` (default `True`) wraps records as `{"meta": {...}, "programs": [...]}`;
  `--bare` disables the wrapper.
- Invalid records (missing `program_url`, unknown fields) go to `errors.jsonl` with the reason.

## Extraction order (first source that works wins)

1. JSON-LD (`<script type="application/ld+json">`) or embedded state JSON
   (`window.__NEXT_DATA__` / `window.X = {...}`)
2. Mastersportal's own markup: `StudyInformationChip`, `QuickFactComponent`,
   `TuitionFeeContainer`, `StartDateItemTime`, language requirement cards
3. HTML labels via BeautifulSoup (generic fallback for any other site)

Listing/search pages (`SearchResultsPage` / `ItemList` JSON-LD) produce no record:
their program links are queued for scraping instead. Listing pagination is followed
automatically through the *next* link (same host only).

## Politeness and blocked sites

- `robots.txt` is checked per domain; disallowed URLs are skipped and logged.
- Per-domain delay + random jitter, retry with exponential backoff (max 3),
  honest browser-like User-Agent and headers (mastersportal/Cloudflare returns
  **403 without** `sec-ch-ua` / `sec-fetch-*` headers).
- On 401/403/429 the site gets a **cooldown** (60s-15min, honouring `Retry-After`)
  and is retried a few times; only after that is the domain stopped for the rest of
  the pass -- never bypassed. The next pass (or run) tries the domain again.
- Tune `USER_AGENT`, `DEFAULT_DELAY`, `MAX_RETRIES`, `MAX_BLOCK_RETRIES` at the top
  of `fetcher.py`.

## Files

| File | Role |
|------|------|
| `scrape.py` | CLI + crawl loop (resume, pagination, link harvesting) |
| `fetcher.py` | HTTP client: robots, delay, headers, retries, blocking |
| `parsers.py` | Per-site parsers + normalisers (`PARSERS` registry) |
| `input_format.py` | Input rules: `urls.txt`, `prompt`, frontier/expanded state |
| `output_format.py` | Output rules: `SCHEMA`, validation, JSONL/JSON writers |
| `urls.txt` / `prompt` | Input URL list + free-text instructions stored in `meta` |
| `run_full.bat` | Driver: loops crawl passes until `--stats` says the crawl is finished |
| `urls_test.txt` / `test_programs.json` | 5-university test input/output |
| `programs.jsonl` | Append-only resume log (one JSON object per line) |
| `errors.jsonl` | Rejected records (url + reason) |
| `frontier.txt` / `expanded.txt` | Persistent crawl state across runs |

## Where to change things

| You want to change... | Edit |
|----------------------|------|
| Input files, comments, dedupe, crawl state | `input_format.py` |
| Output fields / JSON schema / validation | `output_format.py` (`SCHEMA`, `REQUIRED_FIELDS`) |
| Output file names, indent, meta wrapper | `output_format.py` (`OUT_JSON`, `OUT_JSONL`, `WRAP_WITH_META`) |
| Politeness (delay, User-Agent, robots) | `fetcher.py` (top constants) |
| Extraction rules / a new site | `parsers.py` (`PARSERS` registry) |

Nothing else hard-codes input or output details.

## Add a new site parser

1. In `parsers.py`, subclass `BaseParser` and register it in `PARSERS`
   (hostname match, first match wins; unknown hosts fall back to `BaseParser`):

```python
class MySiteParser(BaseParser):
    domains = ("example.ac.uk",)
    source = "example"

    def fill(self, record, soup, jsonld, embedded, html, url):
        super().fill(record, soup, jsonld, embedded, html, url)
        # only set fields the generic pass could not find
        record["field_of_study"] = ...
```

2. Add the site's program pages to `urls.txt`.
3. Re-run `python scrape.py`.
