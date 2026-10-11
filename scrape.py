#!/usr/bin/env python3
"""Polite, resumable CLI scraper: reads urls.txt + prompt -> programs.json.

  python scrape.py --input urls.txt --out programs.json --delay 3

Input rules live in input_format.py, output shape lives in output_format.py.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

import input_format
import output_format
from fetcher import DEFAULT_DELAY, TIMEOUT, BlockedError, FetchError, Fetcher, RobotsDisallowed
from parsers import find_next_url, parser_for

log = logging.getLogger("scrape")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape program pages to JSON.")
    parser.add_argument("--input", default=None, help="URL list file (default: input_format.URLS_FILE)")
    parser.add_argument("--prompt", default=None, help="Prompt file (default: input_format.PROMPT_FILE)")
    parser.add_argument("--out", default=None, help="Final JSON file (default: output_format.OUT_JSON)")
    parser.add_argument("--jsonl", default=None, help="Resume log file (default: output_format.OUT_JSONL)")
    parser.add_argument("--delay", type=float, default=None, help="Seconds between requests per domain")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout seconds")
    parser.add_argument("--no-robots", action="store_true", help="Do NOT check robots.txt (discouraged)")
    parser.add_argument("--no-next", action="store_true", help="Do not follow rel=next pagination links")
    parser.add_argument("--next-limit", type=int, default=None, help="Max pages per URL (default: input_format.MAX_PAGES_PER_URL)")
    parser.add_argument("--fresh", action="store_true", help="Ignore resume log, scrape everything again")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    # 1) input: urls + prompt (formats defined in input_format.py)
    try:
        urls, prompt_text = input_format.load_input(args.input, args.prompt)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 2
    if not urls:
        log.error("No URLs found in %s", args.input or input_format.URLS_FILE)
        return 2
    prompt_file = args.prompt or input_format.PROMPT_FILE
    input_file = args.input or input_format.URLS_FILE
    log.info("input: %d URL(s) from %s | prompt: %d chars from %s", len(urls), input_file, len(prompt_text), prompt_file)

    # 2) resume state
    jsonl_path = Path(args.jsonl) if args.jsonl else None
    if args.fresh:
        records: list[dict] = []
        done: set[str] = set()
        for stale in (output_format.jsonl_path(jsonl_path), output_format.BASE_DIR / output_format.ERRORS_JSONL):
            if stale.exists():
                stale.unlink()
                log.info("--fresh: removed %s", stale.name)
    else:
        records = output_format.read_jsonl(jsonl_path)
        done = {r.get("program_url", "") for r in records if r.get("program_url")}
        if done:
            log.info("resume: %d URL(s) already in %s", len(done), output_format.jsonl_path(jsonl_path).name)

    fetcher = Fetcher(
        delay=args.delay if args.delay is not None else DEFAULT_DELAY,
        timeout=args.timeout if args.timeout is not None else TIMEOUT,
        obey_robots=not args.no_robots,
    )

    counts = {"done": 0, "failed": 0, "skipped": 0, "blocked": 0, "robots": 0}
    try:
        for index, url in enumerate(urls, 1):
            tag = f"[{index}/{len(urls)}]"
            if url in done:
                counts["skipped"] += 1
                log.info("%s skip (already done): %s", tag, url)
                continue
            domain = urlparse(url).netloc
            if domain in fetcher.blocked_domains:
                counts["blocked"] += 1
                log.warning("%s skip (domain blocked): %s", tag, url)
                continue
            try:
                result = fetcher.fetch(url)
            except RobotsDisallowed as exc:
                counts["robots"] += 1
                log.warning("%s skip: %s", tag, exc)
                continue
            except BlockedError as exc:
                counts["blocked"] += 1
                log.error("%s stop domain: %s", tag, exc)
                continue
            except FetchError as exc:
                counts["failed"] += 1
                log.error("%s fetch failed: %s", tag, exc)
                continue

            page_parser = parser_for(url)
            try:
                record = page_parser.parse(result.html, result.final_url or url)
            except Exception as exc:  # a bad page must not kill the run
                counts["failed"] += 1
                log.exception("%s parse failed: %s", tag, url)
                output_format.append_error(url, f"parse error: {exc}")
                continue

            # follow rel="next" pagination and fold every page into this record
            if not args.no_next and input_format.FOLLOW_NEXT_PAGES:
                page_limit = args.next_limit or input_format.MAX_PAGES_PER_URL
                next_url = find_next_url(result.html, url)
                seen_pages = {url}
                pages = 1
                while next_url and pages < page_limit:
                    if next_url in seen_pages or urlparse(next_url).netloc in fetcher.blocked_domains:
                        break
                    seen_pages.add(next_url)
                    try:
                        page = fetcher.fetch(next_url)
                    except (RobotsDisallowed, BlockedError, FetchError) as exc:
                        log.warning("%s pagination stopped: %s", tag, exc)
                        break
                    try:
                        page_record = page_parser.parse(page.html, page.final_url or next_url)
                    except Exception as exc:
                        log.warning("%s pagination parse failed %s: %s", tag, next_url, exc)
                        break
                    record = output_format.merge_records(record, page_record)
                    pages += 1
                    log.info("%s page %d merged (%d listings)", tag, pages, len(record.get("listings") or []))
                    next_url = find_next_url(page.html, next_url)

            ok, reason = output_format.validate(record)
            if not ok:
                counts["failed"] += 1
                output_format.append_error(url, reason)
                log.warning("%s invalid record: %s (%s)", tag, url, reason)
                continue

            output_format.append_jsonl(record, jsonl_path)
            records.append(record)
            done.add(record["program_url"])
            counts["done"] += 1
            log.info(
                "%s ok: %s (%d listings)",
                tag, record.get("program_name") or record.get("page_title") or url,
                len(record.get("listings") or []),
            )
    except KeyboardInterrupt:
        log.warning("interrupted -- writing what we have")
    finally:
        # 3) output: shape defined in output_format.py
        out_path = output_format.write_json(
            records,
            path=args.out,
            prompt_text=prompt_text,
            prompt_file=prompt_file,
            input_file=input_file,
        )
        log.info(
            "finished: %d scraped, %d resumed, %d skipped robots, %d blocked, %d failed",
            counts["done"], counts["skipped"], counts["robots"], counts["blocked"], counts["failed"],
        )
        log.info("output: %s (%d record(s))", out_path, len(records))

    return 1 if counts["failed"] and not counts["done"] else 0


if __name__ == "__main__":
    sys.exit(main())
