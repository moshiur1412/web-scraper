#!/usr/bin/env python3
"""One-off helper: build numbered university batch files from the saved frontier.

Reads _backup/frontier_global.txt (frozen mastersportal listing order), extracts
the /universities/ page URLs, and writes:

  batches/all_universities.txt   numbered master list (# 001 Name)
  batches/batch_01.txt ...       BATCH_SIZE universities per file

Run once:  python make_batches.py
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "_backup" / "frontier_global.txt"
OUT = BASE / "batches"
BATCH_SIZE = 50

UNI_RE = re.compile(r"^https?://www\.mastersportal\.com/universities/\d+/[^/?#]+\.html$", re.I)


def name_from_url(url: str) -> str:
    slug = url.rsplit("/", 1)[-1]
    slug = re.sub(r"\.html$", "", slug, flags=re.I)
    return " ".join(part.capitalize() for part in slug.split("-"))


def main() -> None:
    lines = SRC.read_text(encoding="utf-8-sig").splitlines()
    seen: set[str] = set()
    unis: list[str] = []
    for raw in lines:
        url = raw.strip()
        if not UNI_RE.match(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        unis.append(url)

    OUT.mkdir(parents=True, exist_ok=True)
    # wipe old batch files so a re-run is clean
    for old in OUT.glob("batch_*.txt"):
        old.unlink()

    master_lines = [
        "# All UK universities on mastersportal, in listing order (frozen from the crawl).",
        f"# {len(unis)} universities total. Used to build batches/batch_NN.txt.",
        "",
    ]
    for i, url in enumerate(unis, 1):
        master_lines.append(f"# {i:03d} {name_from_url(url)}")
        master_lines.append(url)
    (OUT / "all_universities.txt").write_text("\n".join(master_lines) + "\n", encoding="utf-8")

    n_batches = (len(unis) + BATCH_SIZE - 1) // BATCH_SIZE
    for b in range(n_batches):
        chunk = unis[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
        first = b * BATCH_SIZE + 1
        last = first + len(chunk) - 1
        lines_out = [
            f"# Batch {b + 1:02d} -- universities {first:03d}-{last:03d} "
            f"({len(chunk)} universities, mastersportal listing order).",
            "# Run:  run_batch.bat " + str(b + 1),
            "",
        ]
        lines_out.extend(chunk)
        path = OUT / f"batch_{b + 1:02d}.txt"
        path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(chunk)} universities ({first:03d}-{last:03d})")

    print(f"all_universities.txt: {len(unis)} universities, {n_batches} batches of up to {BATCH_SIZE}")


if __name__ == "__main__":
    main()
