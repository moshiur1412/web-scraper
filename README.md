# UK University Program Scraper (mastersportal -> one JSON file per university)

Scrapes every master's programme of all **272 UK universities** (~250+ programmes each,
**~70k-100k pages**) from mastersportal into your exact JSON record format.
Missing values are always `null` -- nothing is ever guessed.

**Pipeline:** seed URLs -> `fetcher.py` (robots + delay + browser headers) ->
`parsers.py` (JSON-LD -> embedded state JSON -> HTML) -> `output_format.py`
(schema + validation) -> `programs.jsonl` (resume log) -> **`uk_university/<University Name>.json`**

**Never used this project before?** Follow the sections in order:

| Step | Section | What you get |
|------|---------|--------------|
| 1 | [How it works](#1-how-it-works-flow-diagram) | You understand the files and the flow |
| 2 | [First-time setup](#2-first-time-setup-do-once) | Python + libraries installed (once) |
| 3 | [Test run](#3-test-run-5-universities) | 5 universities scraped in ~2 minutes |
| 4 | [Run the crawl in batches](#4-run-the-crawl-in-batches) | The real crawl, one batch at a time |
| 5 | [Check progress, stop, resume](#5-check-progress-stop-resume) | You always know where the crawl is |
| 6 | [Create batch files for new URLs](#6-create-batch-files-for-new-urls) | You add your own URLs / batches |
| 7-15 | Reference | Estimates, output format, CLI, troubleshooting, file list |

---

## Contents

1. [How it works (flow diagram)](#1-how-it-works-flow-diagram)
2. [First-time setup (do once)](#2-first-time-setup-do-once)
3. [Test run (5 universities)](#3-test-run-5-universities)
4. [Run the crawl in batches](#4-run-the-crawl-in-batches)
5. [Check progress, stop, resume](#5-check-progress-stop-resume)
6. [Create batch files for new URLs](#6-create-batch-files-for-new-urls)
7. [Time and date estimates](#7-time-and-date-estimates)
8. [Output layout (built for huge data)](#8-output-layout-built-for-huge-data)
9. [CLI options](#9-cli-options)
10. [Record rules (accuracy)](#10-record-rules-accuracy)
11. [Politeness and blocked sites](#11-politeness-and-blocked-sites)
12. [Troubleshooting](#12-troubleshooting)
13. [Files](#13-files)
14. [Where to change things](#14-where-to-change-things)
15. [Add a new site parser](#15-add-a-new-site-parser)

---

## 1. How it works (flow diagram)

### 1.1 What one crawl step does

```
        SEED URLs  (your batch files / urls.txt)
                     |
                     v
   +--------------------------------------------------------------+
   | 1. fetcher.py                                                 |
   |    robots.txt check -> delay (~4.5 s) -> browser headers      |
   |    403/429 = cooldown (site is never bypassed)                |
   +----------------------------+---------------------------------+
                                |  HTML page
                                v
   +--------------------------------------------------------------+
   | 2. parsers.py                                                 |
   |    JSON-LD  ->  embedded state JSON  ->  HTML labels          |
   |    one record per programme; a value the page does not state   |
   |    stays null (never guessed)                                 |
   +----------------------------+---------------------------------+
                                |  record
                                v
   +--------------------------------------------------------------+
   | 3. output_format.py  -- validate against the schema           |
   +----+---------------------------+--------------------------+
        |                           |                          |
        v                           v                          v
  programs.jsonl             uk_university/               errors.jsonl
  resume log = source        <University Name>.json       rejected records
  of truth (append-only)     index.json
```

### 1.2 Where the crawl state lives (why nothing is ever lost)

```
  frontier.txt   every URL discovered so far          append-only
  expanded.txt   every URL already fetched            append-only
  programs.jsonl every programme record already saved append-only

  A run only fetches URLs that are NOT in expanded.txt.
  -> close the window, reboot, power cut: run the same command again
     and it continues exactly where it stopped. Nothing is fetched twice.
```

### 1.3 The whole beginner workflow

```
   START
     |
     v
 +-------------------------------+       fails      +-------------------------+
 | 2. FIRST-TIME SETUP (once)    | ----------------> | 12. Troubleshooting     |
 |    python -m venv .venv       |                   +-------------------------+
 |    .venv\Scripts\activate     |
 |    pip install -r requ...txt  |
 +---------------+---------------+
                 | ok
                 v
 +-------------------------------+       fails      +-------------------------+
 | 3. TEST RUN (5 universities)  | ----------------> | 12. Troubleshooting     |
 +---------------+---------------+                   +-------------------------+
                 | ok
                 v
 +--------------------------------------------------------------+
 | 4. run_batch.bat 1          <- one batch = ~50 universities   |
 |    crawls up to 6 h, waits 15 min, repeats until the batch     |
 |    is empty. Everything is appended to crawl_run.log.          |
 +---------------+------------------------------------------------+
                 |
                 v
 +-------------------------------+      work left     +-------------------------+
 | 5. status.bat / --stats       | <----------------- | crawl pass (in run_batch)|
 |    exit 1 = more to do        |                    +-------------------------+
 |    exit 0 = nothing left      |
 +---------------+---------------+
                 |
        +--------+--------+
        |                 |
     exit 1             exit 0
        |                 |
        v                 v
  run the same       +-------------------------------+
  command again      | next: run_batch.bat 2 ... 6  |
  (it resumes)       | or: run_all_batches.bat      |
                     |    (does it all unattended)  |
                     +---------------+---------------+
                                     |
                                     v
                     +---------------------------------------+
                     | uk_university\                       |
                     |   <University Name>.json  (one each) |
                     |   index.json                         |
                     +---------------------------------------+
```

Two rules to remember:

1. **One batch after another** -- never two batches at the same time (they share one
   crawl state and one output folder).
2. **When in doubt, run the same command again.** The crawl always resumes; it never
   starts over unless you pass `--fresh`.

---

## 2. First-time setup (do once)

Do this once on a new computer (or after deleting `.venv`). Everything else is repeated
from [section 4](#4-run-the-crawl-in-batches).

### 2.1 What you need

| Need | Check / note |
|------|--------------|
| Python 3.10+ | `python --version` (see 2.2) |
| This project folder | e.g. `C:\wamp64\www\code\mamun-bhai\scraping` |
| Internet access | the crawl downloads ~72,000 pages over ~5-6 days |
| Disk space | ~0.5-1 GB (crawl state + output) |
| Windows | commands below are for `cmd`; bash alternatives are noted |

### 2.2 Open a terminal in this folder

1. Open **File Explorer** and go to this project folder.
2. Click the **address bar** at the top (where the path is shown).
3. Type `cmd` and press **Enter** -- a black window opens, already in this folder.

The prompt should look like:

```
C:\wamp64\www\code\mamun-bhai\scraping>
```

Every command below is typed into this window.

> PowerShell instead of cmd? Use `powershell` in the address bar. Activation differs:
> `.\.venv\Scripts\Activate.ps1`. Bash / macOS / WSL: `source .venv/bin/activate`.

### 2.3 Check that Python is installed

```bat
python --version
```

Expected: `Python 3.10.x` (or newer).

* Nothing printed / `'python' is not recognized` -> install Python from python.org and
  tick **"Add python.exe to PATH"**, then close and reopen the terminal. See
  [12. Troubleshooting](#12-troubleshooting).
* On some Windows setups only `py` works: use `py` everywhere below instead of `python`.

### 2.4 Create the virtual environment (once)

```bat
python -m venv .venv
```

This creates a `.venv` folder (a private Python just for this project). It takes about
10 seconds and is only needed once -- unless you delete `.venv`.

### 2.5 Activate it (every new terminal window)

```bat
.venv\Scripts\activate
```

The prompt now starts with `(.venv)`:

```
(.venv) C:\wamp64\www\code\mamun-bhai\scraping>
```

> From now on, **open a new terminal = run this line again**. If you forget it, the
> `.bat` drivers still work -- they activate `.venv` by themselves. Typing
> `python scrape.py ...` in a terminal where the venv is **not** active fails with
> `ModuleNotFoundError: No module named 'requests'` -> run `.venv\Scripts\activate` first
> (see [12. Troubleshooting](#12-troubleshooting)).

### 2.6 Install the two libraries (once)

```bat
pip install -r requirements.txt
```

Installs `requests` (HTTP) and `beautifulsoup4` (HTML parsing).

### 2.7 Verify the setup

```bat
python -c "import requests, bs4; print('setup OK')"
```

Expected output: `setup OK`

Done? Go to [section 3](#3-test-run-5-universities).

---

## 3. Test run (5 universities)

Prove the whole pipeline works before starting a multi-day crawl. This fetches **one
programme page from five universities** and writes a small JSON file:

```bat
python scrape.py --input urls_test.txt --out test_programs.json --jsonl test_programs.jsonl --no-frontier --bare --fresh
```

`--no-frontier` means *only* those URLs are fetched and the persistent crawl state is
neither read nor written -- the test can never touch your real crawl.

Result: `test_programs.json` -- Southampton, Surrey, Bath, Glasgow, Edinburgh.
The Southampton record was checked field-by-field against the reference data
(fee 26,200 GBP/year, IELTS 7 / PTE 76 / Duolingo 130, September 2027 intake,
official URL, 60 credits, ...).

Quick look at the result:

```bat
type test_programs.json
```

You should see `program_name`, `tuition_fee`, `language`, `duration`, ... (the full
record layout is in [section 8](#8-output-layout-built-for-huge-data)).

Works? -> [section 4](#4-run-the-crawl-in-batches) (or jump to a bounded batch test:
[4.7](#47-smoke-test-batch-1-the-first-50-universities)).
Fails? -> [section 12](#12-troubleshooting).

---

## 4. Run the crawl in batches

The crawl is split into **6 batches of ~50 universities** so you can run, verify, and
resume one chunk at a time. Batches share one crawl state + one output folder, so run
them **one after another** (never in parallel).

### 4.1 The batch files that already exist

```
batches\
  all_universities.txt   numbered master list (001-272)
  batch_01.txt           universities 001-050
  batch_02.txt           universities 051-100
  ...
  batch_06.txt           universities 251-272 (22 universities)
```

### 4.2 How to run a `.bat` file

**With an argument (what `run_batch.bat` needs) -- type it in the terminal:**

```bat
run_batch.bat 1
```

**Without an argument -- double-click works:**

| File | Double-click OK? | Why |
|------|------------------|-----|
| `run_all_batches.bat` | yes | runs every batch by itself |
| `run_full.bat` | yes | whole-UK crawl from `urls.txt` |
| `status.bat` | yes | prints progress and waits for a key |
| `create_batch.bat` | no (needs your URL file) | run from the terminal |
| `run_batch.bat` | no (needs the batch number) | run from the terminal |

Double-clicking `run_batch.bat` just prints `Usage: run_batch.bat <batch-number>` and
closes again -- that is expected, it needs a number.

Opening the terminal: see [2.2](#22-open-a-terminal-in-this-folder).

### 4.3 `run_batch.bat N` -- crawl ONE batch to completion

```bat
run_batch.bat 1          rem universities 001-050
run_batch.bat 2          rem universities 051-100
...                      rem ...
run_batch.bat 6          rem universities 251-272 (22 universities)
```

Each `run_batch.bat N`:

1. Loads `batches\batch_NN.txt` (the 50 university page URLs for that chunk).
2. Crawls each university's **full catalogue** (paginated, 20/page) then every
   **programme page** -> one JSON record each.
3. Loops **passes** (max 6 h each, 15-min gaps) until that batch's queue is empty.
4. Writes results into the shared `uk_university/` folder as it goes.

> **Expectation for the very first pass:** it is mostly *queue building* -- university
> pages + catalogue pagination at ~4.5 s/page, so a 5-minute window can show
> `finished: 0 records this run` even though hundreds of programme links were queued.
> Records start flowing on the next pass. See [4.7](#47-smoke-test-batch-1-the-first-50-universities).

The window keeps running until the batch is finished; progress is appended to
`crawl_run.log`. When it prints `Batch N complete.`, start the next batch.

### 4.4 `run_all_batches.bat` -- leave it unattended

```bat
run_all_batches.bat
```

Finds **every** `batches\batch_*.txt` (also batches you create yourself later) and runs
them one after another, automatically. Only moves to the next batch when the current one
is fully scraped. Stop it any time (close the window / reboot) and start it again --
it resumes.

### 4.5 Which universities are in which batch?

`batches/all_universities.txt` is the numbered master list (001-272, mastersportal
listing order). Each `batches/batch_NN.txt` header names its range, e.g.:

```
# Batch 01 -- universities 001-050 (50 universities, mastersportal listing order).
# Run:  run_batch.bat 1

https://www.mastersportal.com/universities/189/university-of-surrey.html      <- 001
https://www.mastersportal.com/universities/184/university-of-chester.html     <- 002
...
```

### 4.6 Everything is resumable

The queue lives in `frontier.txt`, finished URLs in `expanded.txt`, saved records in
`programs.jsonl`. Nothing is fetched twice, and nothing is lost if you reboot, close the
window, or the site blocks you -- just run the same `run_batch.bat N` again and it
continues where it stopped.

### 4.7 Smoke-test batch 1 (the first 50 universities)

You do not have to wait a day to see that batch 1 works. Run a **bounded pass**: it stops
by itself after N seconds (`--max-runtime`) or N new records (`--limit`) and keeps the
crawl state, so you can continue later with the normal `run_batch.bat 1`.

```bat
python scrape.py --input batches\batch_01.txt --delay 4 --max-runtime 300 --limit 25 --programs-only --split-by-university
```

Real output of the first bounded pass (5 minutes):

```
input: 50 URL(s) from batches\batch_01.txt | prompt: 3515 chars from prompt
resume: 447 URL(s) already in programs.jsonl
frontier: 2815 URL(s) known | 71 already expanded
[51 | queued 2743] listing /search/master: 102 links (36 new) over 6 page(s) | queue=2779
--max-runtime 300s reached, stopping this pass (2768 URL(s) left for the next run)
finished: 0 records this run, 1 listing page(s) -> 36 link(s) discovered, 0 resumed,
0 robots-skipped, 0 blocked, 0 failed | 447 record(s) on disk
```

**Why 0 records?** The first pass is *queue building*: university page -> catalogue
listing (20 programmes per page, ~4.5 s per page) -> programme links queued. Records are
written from the next pass on, when those programme pages are actually fetched:

```
[1 | queued 2738] ok: University of Bath
[2 | queued 2737] ok: University of Sussex
...
[12 | queued 2727] ok: University of Sussex
output: 2 university file(s) updated in .../uk_university (459 record(s) on disk)
finished: 12 records this run, 1 listing page(s) -> 11 link(s) discovered, 0 resumed,
0 robots-skipped, 0 blocked, 0 failed | 459 record(s) on disk
```

Check the result:

```bat
status.bat
type uk_university\index.json
dir /b uk_university
```

Snapshot after a 4-minute test run (Oct 12, 2026):

| Metric | Before | After |
|--------|--------|-------|
| records in `programs.jsonl` | 447 | 459 |
| universities with programs | 7 | 7 (Bath 79, Sussex 59 rewritten) |
| crawl state | 2815 known / 71 done | 2946 known / 249 done |
| `errors.jsonl` | 0 | 0 |
| output files touched | - | `University of Bath.json`, `University of Sussex.json`, `index.json` |

See the 50 universities of this batch yourself:

```bat
type batches\batch_01.txt
```

---

## 5. Check progress, stop, resume

### 5.1 One command: `status.bat`

```bat
status.bat
```

```
records: 12480 | universities with programs: 50
crawl state: 13204 URL(s) known, 13204 done, 0 still to fetch    <- everything fetched
  ...
Crawl FINISHED - nothing left to fetch.
```

* Exit code `0` = nothing left to fetch (a finished batch prints `BATCH N COMPLETE`),
  `1` = more to do. Top-10 universities by record count are listed too.
* Safe to run **while** the crawl is running -- it only reads the logs, it fetches
  nothing.

The same report per batch file:

```bat
python scrape.py --stats --input batches\batch_01.txt
```

### 5.2 Watch the crawl live

```bat
type crawl_run.log
```

or, in PowerShell:

```powershell
Get-Content crawl_run.log -Tail 50 -Wait
```

### 5.3 Stop it / resume it

| You want to... | Do this |
|----------------|---------|
| Pause the crawl | close the terminal window (or press `Ctrl+C`) |
| Continue later | run the same command again, e.g. `run_batch.bat 1` |
| After a reboot | open the terminal (section 2.2) and run the same command |
| See what is done | `status.bat` |
| Start completely over (**danger**) | add `--fresh` -- deletes the resume log, everything is re-fetched |

### 5.4 Where the state lives

| File | Meaning |
|------|---------|
| `frontier.txt` | every URL discovered so far (append-only) |
| `expanded.txt` | URLs already fetched (append-only) -- the resume point |
| `programs.jsonl` | every saved record (append-only) -- the source of truth |
| `crawl_run.log` | everything the `.bat` drivers printed |
| `errors.jsonl` | rejected records (url + reason) |

---

## 6. Create batch files for new URLs

A "batch file" is just a plain text file with one URL per line. The existing six were
built for you; here is how to make your own.

### 6.1 What a batch file looks like

```bat
# Batch 07 -- URLs 273-275 (3 URLs from my_urls.txt).
# Run:  run_batch.bat 7

https://www.mastersportal.com/universities/189/university-of-surrey.html
https://www.mastersportal.com/studies/488477/english-with-send.html
```

* One URL per line, `#` (or `//`) starts a comment line, blank lines are ignored.
* Works with any mastersportal URL: university pages (`/universities/...`),
  programme pages (`/studies/...`), or a country search page
  (`/search/universities/master/<country>`).
* The file name must be `batches\batch_NN.txt` (zero-padded: `batch_07.txt`, `batch_12.txt`).

### 6.2 Option A (recommended): `create_batch.bat`

1. Put your URLs in a text file inside this project folder, e.g. `my_urls.txt`.
2. Run:

```bat
create_batch.bat my_urls.txt
```

Optional second number = how many URLs per batch file (default 50):

```bat
create_batch.bat my_urls.txt 25
```

It prints exactly what it created and the command to run it:

```
batch_07.txt: 50 URLs (273-322)
...
Created 1 batch file(s): batch_07.txt
Next:  run_batch.bat 7     (or: run_all_batches.bat for every batch)
```

Existing batches (`batch_01` ... `batch_06`) are **never** touched or deleted.

### 6.3 Option B: `make_batches.py` directly

Same thing without the `.bat` wrapper, plus more control:

```bat
python make_batches.py --input my_urls.txt                       rem new batches from my_urls.txt
python make_batches.py --input my_urls.txt --batch-size 25        rem 25 URLs per file
python make_batches.py --input my_urls.txt --start 9              rem start numbering at batch_09
python make_batches.py                                            rem REBUILD batch_01..06 from the saved UK list
```

| Flag | Meaning |
|------|---------|
| `--input FILE` | your URL list (default: the saved `_backup/frontier_global.txt`) |
| `--batch-size N` | URLs per batch file (default 50) |
| `--start N` | first batch number (default: the next free number, e.g. `7`) |
| `--rebuild` | delete all `batches\batch_*.txt` first (automatic when `--input` is omitted) |

Notes:

* Numbers never overwrite an existing batch -- if `batch_03.txt` exists and you ask for
  `--start 3`, it stops with an error and tells you the free number to use.
* `batches/all_universities.txt` gets the new URLs appended (numbering continues).
* Regenerating batch files is always safe: the crawl state (`frontier.txt`,
  `expanded.txt`, `programs.jsonl`) is separate, so already-scraped pages are still
  never fetched twice.

### 6.4 Option C: write it by hand (Notepad)

1. Notepad -> **File > New** -> paste one URL per line.
2. **File > Save As** -> folder: `batches`, file name: `batch_07.txt`
   (choose *Save as type: All Files* so it does not become `batch_07.txt.txt`).
3. Run it: `run_batch.bat 7`

That is all a batch file is -- the generator script only saves you the typing.

### 6.5 Run the new batch

```bat
run_batch.bat 7
```

It behaves exactly like the built-in batches: shares the crawl state, resumes, writes
into `uk_university/`, and shows up automatically in `run_all_batches.bat`.

### 6.6 Change the batch size of the original 6 batches

```bat
python make_batches.py --batch-size 25
```

This **wipes and rebuilds** `batch_01 ...` from the saved UK list (crawl state is kept).

---

## 7. Time and date estimates

Pages to fetch for the whole UK crawl (~270 universities x 250+ programmes):

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

---

## 8. Output layout (built for huge data)

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

---

## 9. CLI options

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

The `.bat` drivers use: `--input <batch> --delay 4 --max-runtime 21600 --programs-only
--split-by-university` and then `--stats` to decide whether the batch is finished.

---

## 10. Record rules (accuracy)

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

---

## 11. Politeness and blocked sites

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

---

## 12. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `'python' is not recognized` | Install Python from python.org and tick **Add python.exe to PATH**, then open a **new** terminal. On some PCs use `py` instead of `python`. |
| `'pip' is not recognized` / the Microsoft Store opens | Use `python -m pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'requests'` | The virtual environment is not active -> run `.venv\Scripts\activate` first (or call `.venv\Scripts\python scrape.py ...`). The `.bat` drivers activate it by themselves. |
| `resume: N URL(s) already in programs.jsonl` | **Not an error** -- the crawl is skipping pages it already saved (resume). |
| `finished: 0 records this run` on the first pass | Normal: the first pass queues catalogue/programme links, records follow on the next pass ([4.7](#47-smoke-test-batch-1-the-first-50-universities)) |
| `'.venv\Scripts\activate' is not recognized` | Setup not done yet -> [2.4 / 2.5](#24-create-the-virtual-environment-once). PowerShell: `.\.venv\Scripts\Activate.ps1`. Bash: `source .venv/bin/activate` |
| `run_batch.bat` prints `Usage:` and the window closes | It needs a number: `run_batch.bat 1` (see [4.2](#42-how-to-run-a-bat-file)) |
| `[ERROR] batches\batch_NN.txt not found` | That batch does not exist yet -> create it ([section 6](#6-create-batch-files-for-new-urls)), or list what exists: `dir /b batches\batch_*.txt` |
| `[ERROR] no batches\batch_*.txt files found` (from `run_all_batches.bat`) | Build them: `python make_batches.py` (original UK list) |
| `[ERROR] no http(s) URLs found in ...` | The URL list is empty or contains only comments / non-http lines |
| Terminal closes the moment you double-click a `.bat` | Run it from an opened terminal instead ([2.2](#22-open-a-terminal-in-this-folder)) |
| `HTTP 429` / `HTTP 403` / Cloudflare in `crawl_run.log` | Normal -- the crawler waits (cooldown) and continues by itself. Do **not** lower `--delay`. If it repeats, just run the same command again later. |
| Crawl stopped, PC rebooted, window closed | Run the same command again -- it resumes ([4.6](#46-everything-is-resumable)) |
| Fewer records than expected | Check `errors.jsonl` (rejected records + reason), then `status.bat` |
| Two batch windows open by mistake | Close one. Batches must run **one after another** |
| Start over from scratch | `python scrape.py --input ... --fresh` -- **deletes** the resume log; everything is re-fetched |
| Want a different output folder / file names | [14. Where to change things](#14-where-to-change-things) |

---

## 13. Files

| File | Role |
|------|------|
| `scrape.py` | CLI + crawl loop (resume, pagination, link harvesting, output) |
| `fetcher.py` | HTTP client: robots, delay, headers, retries, blocking |
| `parsers.py` | Per-site parsers + normalisers (`PARSERS` registry) |
| `input_format.py` | Input rules, crawl state files, country folder naming |
| `output_format.py` | Schema, validation, JSONL/JSON writers, per-university files |
| `make_batches.py` | Builds `batches/` from any URL list (`--input`), or from the saved UK list (default) |
| `create_batch.bat` | Helper: `create_batch.bat my_urls.txt [batch-size]` -> new batch file(s) |
| `run_batch.bat` | Driver: crawls ONE batch (e.g. `run_batch.bat 1`) to completion |
| `run_all_batches.bat` | Driver: finds every `batches\batch_*.txt` and runs them back-to-back |
| `run_full.bat` | Older driver: crawls the whole UK from `urls.txt` (no batching) |
| `status.bat` | Progress report (no fetching); exit `0` = crawl finished |
| `batches/all_universities.txt` | Numbered master list of all seed URLs |
| `batches/batch_01.txt` .. `batch_NN.txt` | Seed files, 50 URLs each by default |
| `urls.txt` / `prompt` | Whole-UK seed + free-text instructions stored in `meta` |
| `programs.jsonl` | Append-only resume log -- the source of truth (one JSON object per line) |
| `uk_university/` | Generated output: one file per university + `index.json` |
| `frontier.txt` / `expanded.txt` | Persistent crawl state across passes |
| `crawl_run.log` | Everything the `.bat` drivers print (append-only) |
| `errors.jsonl` | Rejected records (url + reason) |
| `urls_test.txt` / `test_programs.json` | 5-university test input/output |

---

## 14. Where to change things

| You want to change... | Edit |
|----------------------|------|
| Input files, comments, dedupe, crawl state | `input_format.py` |
| Output fields / JSON schema / validation | `output_format.py` (`SCHEMA`, `REQUIRED_FIELDS`) |
| Output folder / file naming / indent | `input_format.py` (`COUNTRY_CODES`), `output_format.py` (`safe_filename`, `INDENT`) |
| Batch size / new batches / batch numbering | `python make_batches.py --batch-size N --start N`, or `create_batch.bat my_urls.txt N` |
| Pass length / pause between passes / delay | `run_batch.bat` (`PASS_SECONDS`, `PASS_GAP_SECONDS`, `DELAY`) |
| Politeness (delay, User-Agent, robots, cooldowns) | `fetcher.py` (top constants) |
| Extraction rules / a new site | `parsers.py` (`PARSERS` registry) |

---

## 15. Add a new site parser

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
