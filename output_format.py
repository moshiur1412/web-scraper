"""OUTPUT format settings -- edit THIS file to change the JSON output.

  - SCHEMA           = the record shape (add/rename/remove fields here only)
  - REQUIRED_FIELDS  = which fields must be non-empty before a record is kept
  - file names + JSON serialization options
  - validation, JSONL resume log, final pretty JSON writer

Usage in other code:
    from output_format import new_record, validate, append_jsonl, write_json
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent

# --- files -----------------------------------------------------------------
OUT_JSON: str = "programs.json"       # final pretty-printed output
OUT_JSONL: str = "programs.jsonl"     # append-only log -> resume support
ERRORS_JSONL: str = "errors.jsonl"    # rejected records (url + reason)

# --- serialization ---------------------------------------------------------
INDENT: int = 2
ENSURE_ASCII: bool = False            # keep Bengali/UTF-8 readable
WRAP_WITH_META: bool = True           # False -> bare JSON array of records
INCLUDE_PROMPT_TEXT: bool = True      # include prompt file text in meta

# --- validation ------------------------------------------------------------
REQUIRED_FIELDS: tuple[str, ...] = ("program_url",)
MISSING_VALUES: tuple[Any, ...] = (None, "", [], {})

# --- the record schema (missing values = null, never guess) ----------------
SCHEMA: dict[str, Any] = {
    "page_title": None,           # raw <title> of the page (always accurate)
    "program_name": None,
    "university": None,
    "program_url": None,
    "official_program_url": None,
    "degree_type": None,
    "delivered": None,
    "field_of_study": None,
    "duration": {"full_time": None, "part_time": None},
    "start_date": [],
    "apply_date": [],
    "campus_location": None,
    "language": {
        "taught_in": None,
        "requirements": [],  # [{"test": str, "min_score": str}, ...]
    },
    "tuition_fee": {
        "international": {"amount": None, "currency": None, "per": None},
        "domestic": {"amount": None, "currency": None, "per": None},
    },
    "credits": None,
    "academic_requirements": {"gpa": None, "notes": None},
    "living_costs": {"amount": None, "currency": None, "per": None},
    "overview": None,
    "scholarships_available": None,
    # listing pages: entity list from JSON-LD, e.g. universities on a search page
    "listings": [],  # [{"name", "url", "description", "rating": {"value","count","best","worst"}}]
    "source": None,
    "scraped_at": None,
}


def now_iso() -> str:
    """UTC timestamp: 2026-10-10T00:00:00Z"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_record(program_url: str, source: str | None = None) -> dict[str, Any]:
    """Deep-copy the SCHEMA and stamp url/time."""
    record = copy.deepcopy(SCHEMA)
    record["program_url"] = program_url
    record["source"] = source
    record["scraped_at"] = now_iso()
    return record


def is_missing(value: Any) -> bool:
    return value in MISSING_VALUES


def clean(value: Any) -> Any:
    """Recursively strip whitespace from strings; drop empty strings -> None."""
    if isinstance(value, str):
        stripped = " ".join(value.split())
        return stripped or None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value if not is_missing(clean(v))]
    return value


def validate(record: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, reason). Never guess: required fields must be present."""
    for field in REQUIRED_FIELDS:
        if field not in record:
            return False, f"missing schema field: {field}"
        if is_missing(record[field]):
            return False, f"missing required value: {field}"
    unknown = sorted(set(record) - set(SCHEMA))
    if unknown:
        return False, f"fields not in SCHEMA: {', '.join(unknown)}"
    return True, ""


# --- JSONL (resume log) ----------------------------------------------------
def jsonl_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else BASE_DIR / OUT_JSONL


def append_jsonl(record: dict[str, Any], path: str | Path | None = None) -> None:
    """Append one JSON object per line (UTF-8, single line)."""
    p = jsonl_path(path)
    line = json.dumps(record, ensure_ascii=ENSURE_ASCII)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_jsonl(path: str | Path | None = None) -> list[dict[str, Any]]:
    p = jsonl_path(path)
    if not p.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def append_error(url: str, reason: str, path: str | Path | None = None) -> None:
    p = Path(path) if path else BASE_DIR / ERRORS_JSONL
    entry = {"url": url, "reason": reason, "at": now_iso()}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=ENSURE_ASCII) + "\n")


# --- merging (pagination: fold page 2..N into the first record) ------------
def _dedupe(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _merge_value(base: Any, extra: Any) -> Any:
    """Fill missing fields of `base` from `extra`; union lists; dicts merge recursively."""
    if isinstance(base, dict) and isinstance(extra, dict):
        merged = dict(base)
        for key, value in extra.items():
            if key in merged:
                merged[key] = _merge_value(merged[key], value)
            else:
                merged[key] = value
        return merged
    if isinstance(base, list) and isinstance(extra, list):
        return _dedupe(base + extra)
    return base if not is_missing(base) else extra


def merge_records(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Merge a follow-page record into the base record (base wins, lists union)."""
    merged: dict[str, Any] = {}
    for key in SCHEMA:
        merged[key] = _merge_value(copy.deepcopy(base.get(key)), extra.get(key))
    # listings union by url/name (identical descriptions may differ across pages)
    listings = list(base.get("listings") or []) + list(extra.get("listings") or [])
    deduped: dict[str, dict[str, Any]] = {}
    for item in listings:
        if not isinstance(item, dict):
            continue
        key = item.get("url") or item.get("name") or json.dumps(item, ensure_ascii=False)
        deduped.setdefault(str(key).lower(), item)
    merged["listings"] = list(deduped.values())
    merged["program_url"] = base.get("program_url") or extra.get("program_url")
    return merged


# --- final JSON ------------------------------------------------------------
def build_payload(
    records: list[dict[str, Any]],
    prompt_text: str = "",
    prompt_file: str = "",
    input_file: str = "",
) -> Any:
    """What gets written to OUT_JSON (meta wrapper optional)."""
    if not WRAP_WITH_META:
        return records
    meta: dict[str, Any] = {
        "generated_at": now_iso(),
        "input_file": input_file,
        "prompt_file": prompt_file,
        "record_count": len(records),
    }
    if INCLUDE_PROMPT_TEXT:
        meta["prompt"] = prompt_text
    return {"meta": meta, "programs": records}


def write_json(
    records: list[dict[str, Any]],
    path: str | Path | None = None,
    prompt_text: str = "",
    prompt_file: str = "",
    input_file: str = "",
) -> Path:
    """Pretty-printed UTF-8 JSON (ensure_ascii=False)."""
    p = Path(path) if path else BASE_DIR / OUT_JSON
    payload = build_payload(records, prompt_text, prompt_file, input_file)
    text = json.dumps(payload, indent=INDENT, ensure_ascii=ENSURE_ASCII)
    p.write_text(text + "\n", encoding="utf-8")
    return p
