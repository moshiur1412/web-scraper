#!/usr/bin/env python3
"""Polite, resumable CLI scraper: reads urls.txt + prompt -> programs.json.

  python scrape.py --input urls.txt --out programs.json --delay 3

Input rules live in input_format.py, output shape lives in output_format.py.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import input_format
import output_format
from fetcher import DEFAULT_DELAY, TIMEOUT, BlockedError, FetchError, Fetcher, RobotsDisallowed
from parsers import discover, find_next_url, parser_for, program_links

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
    parser.add_argument("--no-frontier", action="store_true", help="Ignore persisted crawl state; only the input URLs are processed")
    parser.add_argument("--bare", action="store_true", help="Write a bare JSON array of records (no meta wrapper)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.bare:
        output_format.WRAP_WITH_META = False

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
    no_frontier: bool = args.no_frontier
    if args.fresh:
        records: list[dict] = []
        done: set[str] = set()
        stale_files = [output_format.jsonl_path(jsonl_path), output_format.BASE_DIR / output_format.ERRORS_JSONL]
        if not no_frontier:
            stale_files += [
                input_format._set_file(input_format.FRONTIER_FILE),
                input_format._set_file(input_format.EXPANDED_FILE),
            ]
        for stale in stale_files:
            if stale.exists():
                stale.unlink()
                log.info("--fresh: removed %s", stale.name)
    else:
        records = output_format.read_jsonl(jsonl_path)
        done = {r.get("program_url", "") for r in records if r.get("program_url")}
        if done:
            log.info("resume: %d URL(s) already in %s", len(done), output_format.jsonl_path(jsonl_path).name)

    # crawl frontier: discovered URLs persist across runs, expanded ones are done
    frontier = [] if no_frontier else input_format.load_frontier()
    expanded: set[str] = set() if no_frontier else input_format.load_expanded()
    log.info("frontier: %d URL(s) known | %d already expanded", len(frontier), len(expanded))

    def remember_frontier(links: list[str]) -> None:
        if not no_frontier:
            input_format.append_frontier(links)

    def remember_expanded(url: str) -> None:
        if not no_frontier:
            input_format.mark_expanded(url)

    fetcher = Fetcher(
        delay=args.delay if args.delay is not None else DEFAULT_DELAY,
        timeout=args.timeout if args.timeout is not None else TIMEOUT,
        obey_robots=not args.no_robots,
    )

    counts = {"records": 0, "failed": 0, "skipped": 0, "blocked": 0, "robots": 0, "listing_pages": 0, "discovered": 0}
    page_limit = args.next_limit or input_format.MAX_PAGES_PER_URL
    follow_next = not args.no_next and input_format.FOLLOW_NEXT_PAGES
    queue: deque[str] = deque()
    queued: set[str] = set()
    for u in [*urls, *frontier]:
        if u not in queued and u not in expanded:
            queued.add(u)
            queue.append(u)
    processed = 0
    try:
        while queue:
            url = queue.popleft()
            processed += 1
            tag = f"[{processed} | queued {len(queue)}]"
            if url in expanded:
                counts["skipped"] += 1
                log.debug("%s skip (already expanded): %s", tag, url)
                continue
            if urlparse(url).netloc in fetcher.blocked_domains:
                counts["blocked"] += 1
                log.debug("%s skip (domain blocked): %s", tag, url)
                if all(urlparse(u).netloc in fetcher.blocked_domains for u in queue):
                    log.warning("every queued URL belongs to a blocked domain -> stopping")
                    break
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

            # --- listing page: discover detail URLs (incl. pagination), no record ---
            is_listing, entities = discover(result.html, url)
            if is_listing:
                pages = 1
                complete = not follow_next
                if follow_next:
                    next_url = find_next_url(result.html, url)
                    seen_pages = {url}
                    chain_ok = True
                    while next_url and pages < page_limit:
                        if next_url in seen_pages:
                            break  # loop back -> chain fully visited
                        if urlparse(next_url).netloc in fetcher.blocked_domains:
                            chain_ok = False
                            break
                        seen_pages.add(next_url)
                        try:
                            page = fetcher.fetch(next_url)
                        except (RobotsDisallowed, BlockedError, FetchError) as exc:
                            log.warning("%s pagination stopped: %s", tag, exc)
                            chain_ok = False
                            break
                        _, more = discover(page.html, next_url)
                        entities.extend(more)
                        pages += 1
                        next_url = find_next_url(page.html, next_url)
                    complete = chain_ok and (next_url is None or next_url in seen_pages)
                new_links = [u for u in dict.fromkeys(entities) if u not in queued and u not in expanded]
                for link in new_links:
                    queued.add(link)
                    queue.append(link)
                remember_frontier(new_links)
                if complete:
                    remember_expanded(url)
                    expanded.add(url)
                else:
                    log.warning("%s listing not fully paginated -> will retry next run", tag)
                counts["listing_pages"] += 1
                counts["discovered"] += len(new_links)
                log.info(
                    "%s listing %s: %d links (%d new) over %d page(s) | queue=%d",
                    tag, urlparse(url).path or "/", len(set(entities)), len(new_links), pages, len(queue),
                )
                continue

            # --- detail page -> one record in the sample format ---
            final_url = result.final_url or url
            if url not in done and final_url not in done:
                page_parser = parser_for(url)
                try:
                    record = page_parser.parse(result.html, final_url)
                except Exception as exc:  # a bad page must not kill the run
                    counts["failed"] += 1
                    log.exception("%s parse failed: %s", tag, url)
                    output_format.append_error(url, f"parse error: {exc}")
                    continue

                ok, reason = output_format.validate(record)
                if not ok:
                    counts["failed"] += 1
                    output_format.append_error(url, reason)
                    log.warning("%s invalid record: %s (%s)", tag, url, reason)
                    continue

                output_format.append_jsonl(record, jsonl_path)
                records.append(record)
                done.add(record["program_url"])
                counts["records"] += 1
                log.info(
                    "%s ok: %s",
                    tag, record.get("university") or record.get("program_name") or url,
                )
            else:
                log.debug("%s record exists -> harvesting links only: %s", tag, url)

            # --- harvest this page's own links (university pages -> programs) ---
            new_links = [
                u for u in program_links(result.html, final_url)
                if u not in queued and u not in expanded
            ]
            if new_links:
                queued.update(new_links)
                queue.extend(new_links)
                remember_frontier(new_links)
                counts["discovered"] += len(new_links)
                log.info("%s %s: %d program link(s) (%d queued)", tag, urlparse(url).path, len(new_links), len(queue))
            remember_expanded(url)
            expanded.add(url)
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
            "finished: %d records, %d listing page(s) -> %d link(s) discovered, "
            "%d resumed, %d robots-skipped, %d blocked, %d failed",
            counts["records"], counts["listing_pages"], counts["discovered"],
            counts["skipped"], counts["robots"], counts["blocked"], counts["failed"],
        )
        log.info("output: %s (%d record(s))", out_path, len(records))

    return 1 if counts["failed"] and not counts["records"] else 0


if __name__ == "__main__":
    sys.exit(main())
