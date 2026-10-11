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
import re
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
EMPTY_LIST_AS_NULL: bool = True   # no data in a list field -> null (else [])

# --- the record schema: EXACT sample format (missing values = null) --------
SCHEMA: dict[str, Any] = {
    "program_name": None,
    "university": None,
    "program_url": None,
    "official_program_url": None,
    "degree_type": None,
    "delivered": None,
    "field_of_study": None,
    "duration": {
        "full_time": None,
        "part_time": None,
    },
    "start_date": [],           # e.g. ["September 2027"]
    "apply_date": [],           # e.g. ["Before July 2027"]
    "campus_location": None,    # e.g. "Southampton, United Kingdom"
    "language": {
        "taught_in": None,
        "requirements": [],     # [{"test": str, "min_score": str}, ...]
    },
    "tuition_fee": {
        "international": {"amount": None, "currency": None, "per": None, "note": None},
        "domestic": {"amount": None, "currency": None, "per": None},
    },
    "credits": None,
    "academic_requirements": {"gpa": None, "notes": None},
    "living_costs": {"amount": None, "currency": None, "per": None},
    "overview": None,
    "scholarships_available": None,
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
    """Recursively strip whitespace from strings; empty string -> None.
    Empty lists -> None when EMPTY_LIST_AS_NULL (no data => null)."""
    if isinstance(value, str):
        stripped = " ".join(value.split())
        return stripped or None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        cleaned = [clean(v) for v in value if not is_missing(clean(v))]
        if not cleaned and EMPTY_LIST_AS_NULL:
            return None
        return cleaned
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


# --- final JSON ------------------------------------------------------------
def group_records(
    records: list[dict[str, Any]], group_by: str | None
) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
    """group_by='university' -> {'University of X': [records...], ...} (stable order)."""
    if not group_by:
        return records
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = record.get(group_by) or "Unknown"
        grouped.setdefault(key, []).append(record)
    return grouped


def build_payload(
    records: list[dict[str, Any]],
    prompt_text: str = "",
    prompt_file: str = "",
    input_file: str = "",
    group_by: str | None = None,
) -> Any:
    """What gets written to OUT_JSON (meta wrapper optional)."""
    body = group_records(records, group_by)
    if not WRAP_WITH_META:
        return body
    meta: dict[str, Any] = {
        "generated_at": now_iso(),
        "input_file": input_file,
        "prompt_file": prompt_file,
        "record_count": len(records),
        "grouped_by": group_by,
    }
    if INCLUDE_PROMPT_TEXT:
        meta["prompt"] = prompt_text
    wrapper = "universities" if group_by == "university" else "programs"
    return {"meta": meta, wrapper: body}


def write_json(
    records: list[dict[str, Any]],
    path: str | Path | None = None,
    prompt_text: str = "",
    prompt_file: str = "",
    input_file: str = "",
    group_by: str | None = None,
    indent: int | None = INDENT,
) -> Path:
    """Pretty-printed UTF-8 JSON (ensure_ascii=False). indent=None -> compact."""
    p = Path(path) if path else BASE_DIR / OUT_JSON
    payload = build_payload(records, prompt_text, prompt_file, input_file, group_by=group_by)
    text = json.dumps(payload, indent=indent, ensure_ascii=ENSURE_ASCII)
    p.write_text(text + "\n", encoding="utf-8")
    return p


# --- one file per university (huge crawls: 272 files instead of one) --------
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str) -> str:
    """'SOAS University of London' -> 'SOAS University of London' (Windows-safe)."""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip(" .")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or "unnamed"


def write_university_files(
    records: list[dict[str, Any]],
    out_dir: str | Path,
    only: set[str] | None = None,
    country_code: str = "",
    indent: int | None = INDENT,
) -> list[Path]:
    """Write <out_dir>/<University Name>.json for each university.

    `only` limits the write to universities touched in this pass (their files are
    the only ones that changed); `index.json` is always rebuilt from the full
    record set so it stays a complete, cheap overview."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    grouped = group_records(records, "university")
    written: list[Path] = []
    for university, programs in grouped.items():
        if only is not None and university not in only:
            continue
        payload = {
            "university": university,
            "country_code": country_code,
            "program_count": len(programs),
            "generated_at": now_iso(),
            "programs": programs,
        }
        path = directory / f"{safe_filename(university)}.json"
        text = json.dumps(payload, indent=indent, ensure_ascii=ENSURE_ASCII)
        path.write_text(text + "\n", encoding="utf-8")
        written.append(path)

    index = {
        "generated_at": now_iso(),
        "country_code": country_code,
        "university_count": len(grouped),
        "program_count": len(records),
        "universities": [
            {"university": uni, "file": f"{safe_filename(uni)}.json", "program_count": len(progs)}
            for uni, progs in grouped.items()
        ],
    }
    (directory / "index.json").write_text(
        json.dumps(index, indent=indent, ensure_ascii=ENSURE_ASCII) + "\n", encoding="utf-8"
    )
    return written
