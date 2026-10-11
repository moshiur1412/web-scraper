# UK University Program Scraper (mastersportal -> one JSON file per university)

Scrapes every master's programme of all **272 UK universities** (~250+ programmes each,
**~70k-100k pages**) from mastersportal into your exact JSON record format.
Missing values are always `null` -- nothing is ever guessed.

**Pipeline:** seed URLs -> `fetcher.py` (robots + delay + browser headers) ->
`parsers.py` (JSON-LD -> embedded state JSON -> HTML) -> `output_format.py`
(schema + validation) -> `programs.jsonl` (resume log) -> **`uk_university/<University Name>.json`**

---

## 1. Setup (once)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Bash: `source .venv/bin/activate` instead.

## 2. Quick start -- run it in batches (recommended)

The crawl is split into **6 batches of ~50 universities** so you can run, verify, and
resume one chunk at a time. Batches share one crawl state + one output folder, so run
them **one after another** (never in parallel).

```bat
run_batch.bat 1          rem universities 001-050
run_batch.bat 2          rem universities 051-100
...                      rem ...
run_batch.bat 6          rem universities 251-272 (22 universities)
```

Or leave the whole thing unattended:

```bat
run_all_batches.bat      rem loops batches 1 -> 6 automatically
```

Each `run_batch.bat N`:

1. Loads `batches/batch_NN.txt` (the 50 university page URLs for that chunk).
2. Crawls each university's **full catalogue** (paginated, 20/page) then every
   **programme page** -> one JSON record each.
3. Loops **passes** (max 6 h each, 15-min gaps) until that batch's queue is empty.
4. Writes results into the shared `uk_university/` folder as it goes.

**Everything is resumable.** The queue lives in `frontier.txt`, finished URLs in
`expanded.txt`, saved records in `programs.jsonl`. Nothing is fetched twice, and nothing
is lost if you reboot, close the window, or the site blocks you -- just run the same
`run_batch.bat N` again and it continues where it stopped.

### Check progress / is a batch done?

```bat
python scrape.py --stats --input batches\batch_01.txt
```

```
records: 12480 | universities with programs: 50
crawl state: 13204 URL(s) known, 13204 done, 0 still to fetch    <- batch 1 finished
```

Exit code `0` = nothing left to fetch (the driver prints `BATCH N COMPLETE`),
`1` = more to do. Top-10 universities by record count are listed too.

### Which universities are in which batch?

`batches/all_universities.txt` is the numbered master list (001-272, mastersportal
listing order). Each `batches/batch_NN.txt` header names its range, e.g.:

```
# Batch 01 -- universities 001-050 (50 universities, mastersportal listing order).
# Run:  run_batch.bat 1

https://www.mastersportal.com/universities/189/university-of-surrey.html      <- 001
https://www.mastersportal.com/universities/184/university-of-chester.html     <- 002
...
```

To change the batch size or regenerate the files: edit `BATCH_SIZE` in
`make_batches.py` and run `python make_batches.py`.

## 3. Time & date estimates (~270 universities x 250+ programmes)

Pages to fetch for the whole UK crawl:

| Phase | What | Pages (approx) |
|-------|------|----------------|
| 1. Universities | 272 university pages | 272 |
| 2. Catalogues | each uni's full catalogue `/search/master?oi=<id>`, 20/page | ~3,500 |
| 3. Programmes | every `/studies/...` page -> one record | ~68,000 (272 x 250) |
| **Total** | | **~72,000 pages** |

At the driver's pace (`--delay 4` = 1 request / ~4.5 s, slow on purpose -- mastersportal
429s anything faster) that is ~15k pages/day realistically (the crawl yields politely to
rate limits instead of pushing through them).

| Batch | Universities | Pages (approx) | Wall-time (approx) | Start -> Done |
|-------|-------------|----------------|--------------------|---------------|
| 1 | 001-050 | 13,200 | ~1 day | Oct 11 -> **Oct 12** |
| 2 | 051-100 | 13,200 | ~1 day | Oct 12 -> **Oct 13** |
| 3 | 101-150 | 13,200 | ~1 day | Oct 13 -> **Oct 14** |
| 4 | 151-200 | 13,200 | ~1 day | Oct 14 -> **Oct 15** |
| 5 | 201-250 | 13,200 | ~1 day | Oct 15 -> **Oct 16** |
| 6 | 251-272 | 6,200 | ~0.5 day | Oct 16 -> **Oct 16/17** |
| **All** | **272** | **~72,000** | **~5-6 days** | **finish ~ Oct 16-17, 2026** |

Notes:

- Theoretical floor (no rate limits) is ~3.7 days; the realistic ~5-6 days bakes in
  mastersportal's 429 cooldowns, which we already hit.
- Batching spreads those rate-limits, so each day's crawl is steadier than one giant run.
- Disk: ~1.5-3 KB of JSONL per record -> **0.3-0.5 GB** crawl state + output.
- Output: ~272 files in `uk_university/` (one per university, 250+ programmes each).

## 4. Output layout (built for huge data)

```
uk_university/
  index.json                              <- overview: all universities + program counts
  University of Southampton.json          <- 402 programs
  University of Surrey.json               <- 250+ programs
  The University of Edinburgh.json
  ...                                      <- ~272 files total
```

The folder name is **derived from the seed URL's country**: `.../master/united-kingdom`
-> `uk_university/`; a US seed (`.../master/united-states`) would produce
`us_university/`. File names are the university names (Windows-safe). Each file:

```json
{
  "university": "University of Southampton",
  "country_code": "uk",
  "program_count": 402,
  "generated_at": "2026-10-11T07:29:02Z",
  "programs": [
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
  ]
}
```

Only the universities that got **new** programmes in a pass are rewritten (a 6-hour pass
that adds 8,000 records touches maybe 40 files, not all 272); `index.json` is always
rebuilt so it always shows the complete picture. `programs.jsonl` (append-only) is the
single source of truth -- every output file can be regenerated from it at any time.

Other output modes (optional):

- `--group-by university` -- one big `programs.json`: `{"meta": ..., "universities": {...}}`
- default (no flags) -- flat `programs.json` array
- `--bare` -- no `meta` wrapper; `--indent 0` -- compact JSON (smaller files)

## 5. CLI options

| Flag | Meaning |
|------|---------|
| `--input batches\batch_01.txt` | URL list file (a batch file, or `urls.txt` for the whole UK) |
| `--delay 4` | Seconds between requests to the same domain (+ 0-1 s jitter) |
| `--timeout 30` | HTTP timeout in seconds |
| `--split-by-university` | Write one file per university into `<country>_university/` |
| `--out-dir DIR` | Folder for `--split-by-university` (default: derived from the seed URL) |
| `--programs-only` | Store program records only (university pages are crawled for links) |
| `--group-by university` | One grouped master file instead of (or as well as) the split files |
| `--out programs.json` | Master file name for the flat/grouped modes |
| `--jsonl programs.jsonl` | Resume log (default: `output_format.OUT_JSONL`) |
| `--indent N` | JSON indent spaces (`0` = compact) |
| `--stats` | Progress report + exit code (`0` = crawl finished, `1` = more to do) |
| `--limit N` | Stop after N new records (smoke tests) |
| `--max-runtime SECONDS` | Stop this pass cleanly after N seconds |
| `--no-next` | Do not follow listing pagination (`rel="next"`) |
| `--next-limit 200` | Max pages per listing (default: `input_format.MAX_PAGES_PER_URL`) |
| `--no-frontier` | Process only the input URLs; ignore `frontier.txt` / `expanded.txt` |
| `--fresh` | **DANGER:** delete the resume log + crawl state and start over |
| `--no-robots` | Skip `robots.txt` checks (discouraged) |
| `-v` | Debug logging |

## 6. Small test run (5 universities)

`urls_test.txt` holds one program page from five different universities.
`--no-frontier` means *only* those URLs are fetched and the persistent crawl state
is neither read nor written.

```bat
python scrape.py --input urls_test.txt --out test_programs.json --jsonl test_programs.jsonl --no-frontier --bare --fresh
```

Result: `test_programs.json` -- Southampton, Surrey, Bath, Glasgow, Edinburgh.
The Southampton record was checked field-by-field against the reference data
(fee 26,200 GBP/year, IELTS 7 / PTE 76 / Duolingo 130, September 2027 intake,
official URL, 60 credits, ...).

## 7. Record rules (accuracy)

- **Never guess.** Any value the page does not state stays `null`.
- **Tuition is always the real fee.** Mastersportal may rewrite the displayed number
  into your local currency; the original amount/currency live in
  `data-original-amount` / `data-original_html` and those are recorded.
  `per` is `"year"`, `"month"`, or `"total"` (one payment for the whole programme).
  Pathway-provider fee boxes (e.g. INTO) are ignored -- only the programme's own fee is kept.
- **Duration is normalised:** `1 year` -> `12 months`.
- **Dates are month+year:** `2027-09-22` -> `September 2027`, deadlines -> `Before July 2027`,
  an open application window stays `Anytime`.
- Invalid records (missing `program_url`, unknown fields) go to `errors.jsonl` with the reason.

### Extraction order (first source that works wins)

1. JSON-LD (`<script type="application/ld+json">`) or embedded state JSON
   (`window.__NEXT_DATA__` / `window.X = {...}`)
2. Mastersportal's own markup: `StudyInformationChip`, `QuickFactComponent`,
   `TuitionFeeContainer`, `StartDateItemTime`, language requirement cards
3. HTML labels via BeautifulSoup (generic fallback for any other site)

## 8. Politeness and blocked sites

- `robots.txt` is checked per domain; disallowed URLs are skipped and logged.
- Per-domain delay + random jitter, retry with exponential backoff (max 3),
  honest browser-like User-Agent and headers (mastersportal/Cloudflare returns
  **403 without** `sec-ch-ua` / `sec-fetch-*` headers).
- On 401/403/429 the site gets a **cooldown** (429: 1 min doubling up to 30 min,
  honouring `Retry-After`; up to ~1.2 h of patience per pass) and is retried a few
  times; only after that is the domain stopped **for the rest of that pass** -- never
  bypassed. The driver waits 15 minutes and the next pass (or batch) tries again.
- Tune `USER_AGENT`, `DEFAULT_DELAY`, `MAX_RETRIES`, `MAX_BLOCK_RETRIES` at the top
  of `fetcher.py`.

## 9. Files

| File | Role |
|------|------|
| `scrape.py` | CLI + crawl loop (resume, pagination, link harvesting, output) |
| `fetcher.py` | HTTP client: robots, delay, headers, retries, blocking |
| `parsers.py` | Per-site parsers + normalisers (`PARSERS` registry) |
| `input_format.py` | Input rules, crawl state files, country folder naming |
| `output_format.py` | Schema, validation, JSONL/JSON writers, per-university files |
| `make_batches.py` | Builds `batches/` from the saved university list (run once) |
| `run_batch.bat` | Driver: crawls ONE batch (e.g. `run_batch.bat 1`) to completion |
| `run_all_batches.bat` | Driver: loops batches 1 -> 6 unattended |
| `run_full.bat` | Older driver: crawls the whole UK from `urls.txt` (no batching) |
| `batches/all_universities.txt` | Numbered master list of all 272 universities |
| `batches/batch_01.txt` .. `batch_06.txt` | 50-university seed files per batch |
| `urls.txt` / `prompt` | Whole-UK seed + free-text instructions stored in `meta` |
| `programs.jsonl` | Append-only resume log -- the source of truth (one JSON object per line) |
| `uk_university/` | Generated output: one file per university + `index.json` |
| `frontier.txt` / `expanded.txt` | Persistent crawl state across passes |
| `errors.jsonl` | Rejected records (url + reason) |
| `urls_test.txt` / `test_programs.json` | 5-university test input/output |

## 10. Where to change things

| You want to change... | Edit |
|----------------------|------|
| Input files, comments, dedupe, crawl state | `input_format.py` |
| Output fields / JSON schema / validation | `output_format.py` (`SCHEMA`, `REQUIRED_FIELDS`) |
| Output folder / file naming / indent | `input_format.py` (`COUNTRY_CODES`), `output_format.py` (`safe_filename`, `INDENT`) |
| Batch size / batch files | `make_batches.py` (`BATCH_SIZE`), then re-run it |
| Politeness (delay, User-Agent, robots, cooldowns) | `fetcher.py` (top constants) |
| Extraction rules / a new site | `parsers.py` (`PARSERS` registry) |

## 11. Add a new site parser

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

2. Add the site's program pages to `urls.txt` (or a batch file).
3. Re-run `python scrape.py`.
