#!/usr/bin/env python3
"""Build batch seed files (batches/batch_NN.txt) from a list of URLs.

Two ways to use it:

  1) Rebuild the original UK batches (deletes old batch_*.txt first):

         python make_batches.py

     source: _backup/frontier_global.txt -> batch_01 .. batch_06 (50 each)

  2) Turn ANY file of NEW URLs into new batches (existing batches are kept,
     the new files start at the next free number -> batch_07, batch_08, ...):

         python make_batches.py --input my_urls.txt
         python make_batches.py --input my_urls.txt --batch-size 25
         python make_batches.py --input my_urls.txt --start 9

A source file is simply one URL per line; '#' (or '//') lines are comments and
non-http lines are ignored. Then run the result with:   run_batch.bat <number>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "_backup" / "frontier_global.txt"
OUT = BASE / "batches"
BATCH_SIZE = 50
MASTER_LIST = "all_universities.txt"

UNI_RE = re.compile(r"^https?://www\.mastersportal\.com/universities/\d+/[^/?#]+\.html$", re.I)
BATCH_FILE_RE = re.compile(r"^batch_(\d+)\.txt$", re.I)
HTTP_RE = re.compile(r"^https?://", re.I)


def name_from_url(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.html?$", "", slug, flags=re.I)
    return " ".join(part.capitalize() for part in slug.split("-") if part) or url


def read_urls(path: Path) -> list[str]:
    """Non-comment, http(s) lines, de-duplicated (first occurrence wins)."""
    seen: set[str] = set()
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        url = raw.strip()
        if not url or url.startswith(("#", "//")) or not HTTP_RE.match(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def existing_batch_numbers(directory: Path) -> list[int]:
    numbers = []
    for path in directory.glob("batch_*.txt"):
        m = BATCH_FILE_RE.match(path.name)
        if m:
            numbers.append(int(m.group(1)))
    return sorted(numbers)


def urls_in_batches_before(directory: Path, before: int) -> int:
    """How many URLs live in batch_01..batch_(before-1) -> global numbering offset."""
    total = 0
    for path in directory.glob("batch_*.txt"):
        m = BATCH_FILE_RE.match(path.name)
        if m and int(m.group(1)) < before:
            total += len(read_urls(path))
    return total


def master_list_length(directory: Path) -> int:
    path = directory / MASTER_LIST
    return len(read_urls(path)) if path.exists() else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build batches/batch_NN.txt seed files from a URL list.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  python make_batches.py\n"
               "  python make_batches.py --input my_urls.txt\n"
               "  python make_batches.py --input my_urls.txt --batch-size 25\n"
               "  python make_batches.py --input my_urls.txt --start 7\n",
    )
    ap.add_argument("--input", "-i", default=None, metavar="FILE",
                    help=f"URL list to turn into batches (default: {SRC.relative_to(BASE)})")
    ap.add_argument("--batch-size", "-n", type=int, default=BATCH_SIZE, metavar="N",
                    help=f"URLs per batch file (default: {BATCH_SIZE})")
    ap.add_argument("--start", "-s", type=int, default=None, metavar="N",
                    help="first batch number to write (default: 1 when rebuilding, "
                         "otherwise the next free batch number)")
    ap.add_argument("--rebuild", action="store_true",
                    help="delete all existing batch_*.txt first (automatic when --input is omitted)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_size < 1:
        print("[ERROR] --batch-size must be at least 1", file=sys.stderr)
        return 2

    src = Path(args.input) if args.input else SRC
    if not src.is_absolute() and args.input:
        src = Path.cwd() / src
    if not src.exists():
        print(f"[ERROR] source not found: {src}\n"
              f"        Give your own URL list:  python make_batches.py --input my_urls.txt",
              file=sys.stderr)
        return 2

    default_source = args.input is None
    rebuild = args.rebuild or default_source
    OUT.mkdir(parents=True, exist_ok=True)

    numbers = existing_batch_numbers(OUT)
    if args.start is None:
        start = 1 if rebuild else (max(numbers) + 1 if numbers else 1)
    else:
        start = args.start
    if start < 1:
        print("[ERROR] --start must be at least 1", file=sys.stderr)
        return 2
    if not rebuild and numbers and start <= max(numbers):
        print(f"[ERROR] batches/batch_{start:02d}.txt already exists.\n"
              f"        Use --start {max(numbers) + 1} to add new batches after it, "
              f"or --rebuild to wipe all batch files first.",
              file=sys.stderr)
        return 2

    urls = read_urls(src)
    if default_source:
        # the frozen frontier contains every discovered URL; batches are built
        # from the university pages only (original behaviour)
        urls = [u for u in urls if UNI_RE.match(u)]
    if not urls:
        print(f"[ERROR] no http(s) URLs found in {src}", file=sys.stderr)
        return 2

    if rebuild:
        for old in OUT.glob("batch_*.txt"):
            old.unlink()

    offset = 0 if rebuild else urls_in_batches_before(OUT, start)
    label = "universities" if all(UNI_RE.match(u) for u in urls) else "URLs"
    size = args.batch_size

    created: list[int] = []
    for i in range(0, len(urls), size):
        chunk = urls[i : i + size]
        n = start + i // size
        first = offset + i + 1
        last = first + len(chunk) - 1
        if default_source:
            head = (f"# Batch {n:02d} -- universities {first:03d}-{last:03d} "
                    f"({len(chunk)} universities, mastersportal listing order).")
        else:
            head = (f"# Batch {n:02d} -- {label} {first:03d}-{last:03d} "
                    f"({len(chunk)} {label} from {src.name}).")
        path = OUT / f"batch_{n:02d}.txt"
        path.write_text("\n".join([head, f"# Run:  run_batch.bat {n}", "", *chunk]) + "\n",
                        encoding="utf-8")
        created.append(n)
        print(f"{path.name}: {len(chunk)} {label} ({first:03d}-{last:03d})")

    # master list: rebuild it in rebuild mode, append to it when adding new batches
    master = OUT / MASTER_LIST
    if rebuild:
        master_lines = [
            "# All UK universities on mastersportal, in listing order (frozen from the crawl).",
            f"# {len(urls)} universities total. Used to build batches/batch_NN.txt.",
            "",
        ]
        for i, url in enumerate(urls, 1):
            master_lines.append(f"# {i:03d} {name_from_url(url)}")
            master_lines.append(url)
        master.write_text("\n".join(master_lines) + "\n", encoding="utf-8")
        print(f"{MASTER_LIST}: {len(urls)} {label}")
    else:
        start_at = master_list_length(OUT) or (offset + 1)
        lines: list[str] = []
        if not master.exists():
            lines += ["# Master list of all seed URLs (built by make_batches.py).", ""]
        else:
            lines += ["", f"# --- added by make_batches.py --input {src.name} ---"]
        for i, url in enumerate(urls):
            n = start_at + i
            lines.append(f"# {n:03d} {name_from_url(url)}")
            lines.append(url)
        with master.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"{MASTER_LIST}: appended {len(urls)} {label} (from {start_at:03d})")

    print(f"\nCreated {len(created)} batch file(s): " +
          ", ".join(f"batch_{n:02d}.txt" for n in created))
    print("Next:  run_batch.bat " + str(created[0]) +
          ("  ...  run_batch.bat " + str(created[-1]) if len(created) > 1 else "") +
          "     (or: run_all_batches.bat for every batch)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
