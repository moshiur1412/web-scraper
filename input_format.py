"""INPUT format settings -- edit THIS file to change how input is read.

Nothing else in the project hard-codes input details:
  - which files to read (URLS_FILE, PROMPT_FILE)
  - how lines are parsed (comments, blanks, scheme filter, dedupe)

Usage in other code:
    from input_format import load_input
    urls, prompt = load_input()
"""
from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- files -----------------------------------------------------------------
URLS_FILE: str = "urls.txt"   # one URL per line
PROMPT_FILE: str = "prompt"   # free-text instructions -> stored in output meta

# --- line rules ------------------------------------------------------------
COMMENT_PREFIXES: tuple[str, ...] = ("#", "//")
ALLOWED_SCHEMES: tuple[str, ...] = ("http", "https")
DEDUPLICATE: bool = True      # keep first occurrence only
SKIP_INVALID_LINES: bool = True  # drop lines that are not http(s) URLs

# --- crawling --------------------------------------------------------------
FOLLOW_NEXT_PAGES: bool = True   # follow rel="next" links (listing pagination)
MAX_PAGES_PER_URL: int = 50      # safety cap per input URL


def read_lines(path: Path) -> list[str]:
    """Return non-empty, non-comment lines (stripped) from a text file."""
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith(COMMENT_PREFIXES):
            continue
        lines.append(line)
    return lines


def load_urls(path: str | Path | None = None) -> list[str]:
    """Read the URL list from `path` (default: URLS_FILE next to this file)."""
    p = Path(path) if path else BASE_DIR / URLS_FILE
    urls = [ln for ln in read_lines(p) if ln.lower().startswith(ALLOWED_SCHEMES)]
    if not SKIP_INVALID_LINES:
        urls = read_lines(p)
    if DEDUPLICATE:
        urls = list(dict.fromkeys(urls))
    return urls


def load_prompt(path: str | Path | None = None) -> str:
    """Read the prompt/instructions file (empty string if missing)."""
    p = Path(path) if path else BASE_DIR / PROMPT_FILE
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8-sig").strip()


def load_input(
    urls_path: str | Path | None = None,
    prompt_path: str | Path | None = None,
) -> tuple[list[str], str]:
    """Convenience: read both inputs at once -> (urls, prompt_text)."""
    return load_urls(urls_path), load_prompt(prompt_path)
