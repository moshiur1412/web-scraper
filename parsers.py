"""Parsers -- rules-based extraction, in order:
  1. JSON-LD (<script type="application/ld+json">)
  2. Embedded state JSON (window.__NEXT_DATA__ / window.X = {...})
  3. HTML labels via BeautifulSoup

Parsers are pluggable: one class per domain (see PARSERS registry),
selected by hostname in parser_for(). Never guess -- missing data stays null.
"""
from __future__ import annotations

import json
import re
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import output_format
from output_format import new_record

# --- small helpers ---------------------------------------------------------

_LABEL_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "dt", "th", "strong", "b", "em", "span", "p", "li"]

_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(year|month|week|day|semester)s?\b", re.I)
_SYMBOLS = {"£": "GBP", "€": "EUR", "₹": "INR", "৳": "BDT", "¥": "JPY", "￥": "JPY", "₩": "KRW"}
_CURRENCY_CODES = re.compile(r"\b(USD|EUR|GBP|BDT|AUD|CAD|INR|JPY|CNY|NZD|ZAR|AED|SAR|SEK|NOK|DKK|CHF)\b", re.I)
_AMOUNT_RE = re.compile(r"\d[\d,\s]*\.?\d*")
_PER_RE = re.compile(r"(?:\bper\b|/)\s*(year|month|semester|term|credit|week)s?\b|\bannually\b", re.I)
_TEST_RE = (
    r"\b(IELTS(?:\s+Academic)?|PTE(?:\s+Academic)?|TOEFL(?:\s+iBT)?|"
    r"Duolingo(?:\s+English\s+Test)?|Cambridge\s+English|C1\s+Advanced|C2\s+Advanced)\b"
)
_TEST_BEFORE = re.compile(_TEST_RE + r"[^0-9]{0,30}(\d+(?:\.\d+)?)", re.I)
_TEST_AFTER = re.compile(r"(\d+(?:\.\d+)?)\s*(?:score\s*(?:in|of)\s*)?" + _TEST_RE, re.I)


def as_str(value: Any) -> str | None:
    """JSON-LD values can be str | dict | list -- flatten to a clean string."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return as_str(value.get("name") or value.get("@id") or "")
    if isinstance(value, list):
        for item in value:
            s = as_str(item)
            if s:
                return s
    return None


def to_list(value: Any) -> list[str]:
    """Scalar -> [value]; split multi-values on ';' or '|'; [] otherwise."""
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        parts = re.split(r"\s*[;|]\s*", str(value).strip())
        return [p for p in (x.strip() for x in parts) if p]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(to_list(item))
        return out
    return []


def norm_duration(value: Any) -> str | None:
    """'1 year' -> '12 months', '18 Months' -> '18 months' (keep other text)."""
    if not isinstance(value, str) or not value.strip():
        return as_str(value)
    text = " ".join(value.split())
    m = _DURATION_RE.search(text)
    if not m:
        return text
    number = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "year":
        months = int(round(number * 12))
    elif unit == "month":
        months = int(round(number))
    elif unit == "semester":
        months = int(round(number * 6))
    else:
        return text  # weeks/days: keep original wording
    replacement = f"{months} month{'s' if months != 1 else ''}"
    return (text[: m.start()] + replacement + text[m.end() :]).strip()


def parse_money(text: Any) -> dict[str, Any] | None:
    """'£12,000 per year' -> {'amount': 12000, 'currency': 'GBP', 'per': 'year'}.
    '$' is ambiguous -> currency stays None (never guess)."""
    if not isinstance(text, str) or not text.strip():
        return None
    currency: str | None = None
    anchor = 0
    m = _CURRENCY_CODES.search(text)
    if m:
        currency, anchor = m.group(1).upper(), m.start()
    else:
        for sym, code in _SYMBOLS.items():
            if sym in text:
                currency, anchor = code, text.index(sym)
                break
    amount: int | float | None = None
    window_start = max(0, anchor - 5)
    nearby = _AMOUNT_RE.search(text, window_start)
    mnum = nearby or _AMOUNT_RE.search(text)
    if mnum:
        raw = mnum.group(0).replace(",", "").replace(" ", "").strip(".")
        try:
            num = float(raw)
            amount = int(num) if num.is_integer() else num
        except ValueError:
            amount = None
    per: str | None = None
    mp = _PER_RE.search(text)
    if mp:
        per = next((g for g in mp.groups() if g), None)
        if per:
            per = per.lower()
        elif mp.group(0).lower() in ("annually", "per year"):
            per = "year"
    if amount is None and currency is None and per is None:
        return None
    return {"amount": amount, "currency": currency, "per": per}


def norm_mode(value: Any) -> str | None:
    v = as_str(value)
    if not v:
        return None
    low = v.lower()
    if "blended" in low or "hybrid" in low:
        return "Blended"
    if "online" in low and not any(x in low for x in ("on campus", "on-campus", "on site", "on-site")):
        return "Online"
    if any(x in low for x in ("on campus", "on-campus", "on site", "on-site", "campus")):
        return "On Campus"
    return v


def language_tests(html_text: str, limit: int = 6) -> list[dict[str, str]]:
    """Find 'IELTS 7' / 'Duolingo English Test 130' style requirement pairs."""
    found: dict[str, str] = {}
    for m in _TEST_BEFORE.finditer(html_text):
        test, score = " ".join(m.group(1).split()), m.group(2)
        found.setdefault(test.lower(), {"test": test, "min_score": score})
    for m in _TEST_AFTER.finditer(html_text):
        score, test = m.group(1), " ".join(m.group(2).split())
        found.setdefault(test.lower(), {"test": test, "min_score": score})
    return list(found.values())[:limit]


def meta_content(soup: BeautifulSoup, *keys: str) -> str | None:
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return tag["content"].strip() or None
    return None


def clean_title(text: str | None) -> tuple[str | None, str | None]:
    """'MSc Data | University X' -> ('MSc Data', 'University X')"""
    if not text:
        return None, None
    parts = re.split(r"\s+[|–—]\s+", " ".join(text.split()), maxsplit=1)
    name = parts[0].strip() or None
    org = parts[1].strip() if len(parts) > 1 else None
    return name, org


def label_value(soup: BeautifulSoup, labels: tuple[str, ...], max_len: int = 200) -> str | None:
    """Find a short label tag ('Start date:') and return the value near it."""
    wanted = {_norm_label(x) for x in labels}
    for tag in soup.find_all(_LABEL_TAGS):
        txt = tag.get_text(" ", strip=True)
        if not txt or len(txt) > 80 or _norm_label(txt) not in wanted:
            continue
        value: str | None = None
        for sib in tag.find_next_siblings(limit=3):
            v = sib.get_text(" ", strip=True)
            if v and _norm_label(v) != _norm_label(txt):
                value = v
                break
        if not value:
            parent = tag.parent
            if parent is not None:
                full = parent.get_text(" ", strip=True)
                idx = full.lower().find(txt.lower())
                if idx >= 0:
                    value = full[idx + len(txt) :]
        if value:
            value = value.strip(" \t:|-–—,")
            if value and len(value) <= max_len:
                return value
    return None


def _norm_label(text: str) -> str:
    return " ".join(text.split()).rstrip(": ").lower()


def search(obj: Any, names: tuple[str, ...], max_depth: int = 5, max_nodes: int = 2000) -> Any:
    """Breadth-first search for a scalar value under any of `names` (case-insensitive)."""
    wanted = {n.lower() for n in names}
    queue: deque[tuple[Any, int]] = deque([(obj, 0)])
    seen = 0
    while queue and seen < max_nodes:
        node, depth = queue.popleft()
        seen += 1
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.lower() in wanted and _scalarish(value):
                    return value
                if depth < max_depth and isinstance(value, (dict, list)):
                    queue.append((value, depth + 1))
        elif isinstance(node, list) and depth < max_depth:
            for item in node:
                if isinstance(item, (dict, list)):
                    queue.append((item, depth + 1))
    return None


def _scalarish(value: Any) -> bool:
    if isinstance(value, bool) or isinstance(value, (str, int, float)):
        return True
    return isinstance(value, list) and 0 < len(value) <= 10 and all(
        isinstance(x, (str, int, float)) for x in value
    )


# --- extraction steps ------------------------------------------------------

def jsonld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for tag in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        text = tag.string or tag.get_text() or ""
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and "@graph" in item:
                objects.extend(x for x in item["@graph"] if isinstance(x, dict))
            elif isinstance(item, dict):
                objects.append(item)
    return objects


_PREFERRED_TYPES = {"course", "program", "collegeoruniversity", "educationalorganization", "educationaloccupationalprogram"}
_LISTING_TYPES = {"searchresultspage", "itemlist"}


def _types(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type") or []
    items = raw if isinstance(raw, list) else [raw]
    return {str(t).lower() for t in items}


def is_listing_page(jsonld: list[dict[str, Any]]) -> bool:
    """True for search/list pages (SearchResultsPage / ItemList), not program pages."""
    listing = False
    for node in jsonld:
        types = _types(node)
        if types & _PREFERRED_TYPES:
            return False  # a real program/organisation page wins
        if types & _LISTING_TYPES:
            listing = True
    return listing


def _rating_block(raw: Any) -> dict[str, Any]:
    block: dict[str, Any] = {"value": None, "count": None, "best": None, "worst": None}
    if isinstance(raw, dict):
        block["value"] = raw.get("ratingValue")
        block["count"] = raw.get("ratingCount", raw.get("reviewCount"))
        block["best"] = raw.get("bestRating")
        block["worst"] = raw.get("worstRating")
    return block


def extract_listings(jsonld: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entity list of a listing page (JSON-LD mainEntity / itemListElement)."""
    out: list[dict[str, Any]] = []
    for node in jsonld:
        if not (_types(node) & _LISTING_TYPES):
            continue
        raw = node.get("mainEntity") or node.get("itemListElement") or []
        if isinstance(raw, dict):
            raw = [raw]
        for item in raw:
            if not isinstance(item, dict):
                continue
            if str(item.get("@type", "")).lower() == "listitem":
                item = item.get("item") or {}
                if not isinstance(item, dict):
                    continue
            name = as_str(item.get("name"))
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "url": as_str(item.get("url")),
                    "description": as_str(item.get("description")),
                    "rating": _rating_block(item.get("aggregateRating")),
                }
            )
    return out


def find_next_url(html: str, base_url: str) -> str | None:
    """Find the 'next page' link on the same host.

    Handles <link rel="next">, <a rel="next"> and pagination anchors
    (<a name="next" aria-label="Next page">, rel="nofollow" is normal for pagination).
    """
    patterns = (
        r'<link[^>]+rel="next"[^>]*href="([^"]+)"',
        r'<link[^>]+href="([^"]+)"[^>]*rel="next"',
        r'<a[^>]+rel="next"[^>]*href="([^"]+)"',
        r'<a[^>]+href="([^"]+)"[^>]*rel="next"',
        r'<a[^>]+href="([^"]+)"[^>]*(?:name="next"|aria-label="Next page")',
        r'<a[^>]+(?:name="next"|aria-label="Next page")[^>]+href="([^"]+)"',
    )
    host = urlparse(base_url).netloc
    for pattern in patterns:
        m = re.search(pattern, html, re.I)
        if not m:
            continue
        nxt = urljoin(base_url, m.group(1).strip())
        if urlparse(nxt).netloc == host:
            return nxt
    return None


def primary_node(objects: list[dict[str, Any]]) -> dict[str, Any] | None:
    fallback: dict[str, Any] | None = None
    for obj in objects:
        if not isinstance(as_str(obj.get("name")), str):
            continue
        types = obj.get("@type") or []
        types = [types] if isinstance(types, str) else types
        if any(str(t).lower() in _PREFERRED_TYPES for t in types):
            return obj
        if fallback is None and ("description" in obj or "provider" in obj):
            fallback = obj
    if fallback:
        return fallback
    for obj in objects:
        if isinstance(obj.get("name"), str):
            return obj
    return None


def embedded_json(soup: BeautifulSoup) -> dict[str, Any]:
    """State JSON: known script ids/types first, then `window.X = {...}`."""
    for tag in soup.find_all("script"):
        text = tag.string or tag.get_text() or ""
        if len(text) < 2 or not text.strip():
            continue
        sid = f"{tag.get('id', '')} {tag.get('data-testid', '')}".lower()
        known = any(k in sid for k in ("next_data", "initial_state", "nuxt", "state", "app-data"))
        if known or tag.get("type") == "application/json":
            try:
                obj = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(obj, dict) and obj:
                return obj
    decoder = json.JSONDecoder()
    for tag in soup.find_all("script"):
        text = tag.string or tag.get_text() or ""
        if "{" not in text or "=" not in text or len(text) > 5_000_000:
            continue
        for m in re.finditer(r"(?:window\.)?[A-Za-z_$][\w$.]*\s*=\s*", text):
            i = m.end()
            if i >= len(text) or text[i] not in "[{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[i:])
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(obj, dict) and obj:
                return obj
    return {}


# --- parser classes --------------------------------------------------------

class BaseParser:
    """Common interface: subclasses only set domains/source and may override fill()."""

    domains: tuple[str, ...] = ()
    source: str | None = None
    default_fee_bucket: str = "international"  # where an unlabelled tuition fee goes

    def parse(self, html: str, url: str) -> dict[str, Any]:
        record = new_record(url, source=self.source or urlparse(url).netloc)
        soup = BeautifulSoup(html, "html.parser")
        self.fill(
            record,
            soup=soup,
            jsonld=jsonld_objects(soup),
            embedded=embedded_json(soup),
            html=html,
            url=url,
        )
        return output_format.clean(record)

    def fill(
        self,
        record: dict[str, Any],
        soup: BeautifulSoup,
        jsonld: list[dict[str, Any]],
        embedded: dict[str, Any],
        html: str,
        url: str,
    ) -> None:
        node = primary_node(jsonld) or {}
        page_host = urlparse(url).netloc
        record["page_title"] = soup.title.get_text(strip=True) if soup.title else None
        title_name, title_org = clean_title(record["page_title"])
        h1 = soup.h1.get_text(" ", strip=True) if soup.h1 else None
        site_name = meta_content(soup, "og:site_name")

        # --- listing/search page: only page meta + entity list (no guesses) ---
        if is_listing_page(jsonld):
            record["program_name"] = None
            record["university"] = None
            record["overview"] = (
                as_str(node.get("description"))
                or meta_content(soup, "description", "og:description")
            )
            record["listings"] = extract_listings(jsonld)
            return

        # --- program page: names / links -------------------------------------
        if title_org and site_name and title_org.lower() == site_name.lower():
            title_org = None  # 'Mastersportal' is the publisher, not a university
        record["program_name"] = as_str(node.get("name")) or h1 or title_name
        record["university"] = (
            as_str(node.get("provider")) or as_str(node.get("organizer"))
            or as_str(search(embedded, ("university", "institution", "organisation_name", "organization_name")))
            or title_org
        )
        record["overview"] = (
            as_str(node.get("description")) or meta_content(soup, "description", "og:description")
        )
        record["official_program_url"] = self._official_url(node, soup, embedded, url, page_host)

        # degree / field / mode / duration
        record["degree_type"] = (
            as_str(node.get("educationalCredentialAwarded")) or as_str(node.get("credentialAwarded"))
            or as_str(search(embedded, ("degree_type", "qualification", "credential_award")))
            or label_value(soup, ("Degree", "Award", "Qualification", "Credential"))
        )
        record["field_of_study"] = (
            as_str(node.get("about"))
            or as_str(search(embedded, ("field_of_study", "subject_area", "discipline")))
        )
        record["delivered"] = norm_mode(
            label_value(soup, ("Study mode", "Mode of study", "Delivery mode", "Mode of delivery", "Attendance"))
            or search(embedded, ("delivery_mode", "study_mode", "mode_of_study", "attendance"))
        )
        record["duration"] = self._duration(soup, embedded, node)
        record["credits"] = self._credits(soup, embedded)

        # dates / place / language
        record["start_date"] = to_list(
            label_value(soup, ("Start date", "Start dates", "Intake", "Intakes", "Application start"))
            or search(embedded, ("start_date", "startdate", "intake", "intakes"))
        )
        record["apply_date"] = to_list(
            label_value(soup, ("Application deadline", "Application deadlines", "Apply by", "Deadline"))
            or search(embedded, ("apply_date", "application_deadline", "deadline"))
        )
        record["campus_location"] = self._location(node, soup, embedded)
        record["language"]["taught_in"] = (
            as_str(node.get("inLanguage"))
            or label_value(soup, ("Language of instruction", "Taught in", "Teaching language"))
            or as_str(search(embedded, ("language_of_instruction", "taught_in", "teaching_language")))
        )
        record["language"]["requirements"] = language_tests(soup.get_text(" ", strip=True)[:200_000])

        # money / requirements
        record["tuition_fee"] = self._tuition(soup, embedded)
        record["living_costs"] = parse_money(
            label_value(soup, ("Living cost", "Living costs", "Estimated living costs", "Cost of living"))
        ) or {"amount": None, "currency": None, "per": None}
        gpa = label_value(soup, ("GPA", "Minimum GPA", "GPA requirement")) or as_str(
            search(embedded, ("gpa", "minimum_gpa", "gpa_requirement"))
        )
        record["academic_requirements"]["gpa"] = gpa
        record["scholarships_available"] = self._scholarships(embedded)

    # --- field builders ----------------------------------------------------
    @staticmethod
    def _official_url(
        node: dict[str, Any], soup: BeautifulSoup, embedded: dict[str, Any], url: str, page_host: str
    ) -> str | None:
        explicit = as_str(
            search(embedded, ("official_url", "official_program_url", "university_url", "provider_url"))
        )
        if explicit:
            return explicit
        for candidate in (as_str(node.get("url")), (soup.find("link", rel="canonical") or {}).get("href")):
            if candidate and urlparse(candidate).netloc and urlparse(candidate).netloc != page_host:
                return candidate
        return None

    @staticmethod
    def _duration(soup: BeautifulSoup, embedded: dict[str, Any], node: dict[str, Any]) -> dict[str, str | None]:
        raw_full = (
            norm_duration(search(embedded, ("full_time", "fulltime", "duration", "course_duration")))
            or norm_duration(label_value(soup, ("Duration", "Course duration", "Programme duration")))
            or norm_duration(as_str(node.get("timeRequired")))
        )
        raw_part = norm_duration(
            search(embedded, ("part_time", "parttime")) or label_value(soup, ("Part time duration", "Part-time duration"))
        )
        return {"full_time": raw_full, "part_time": raw_part}

    @staticmethod
    def _credits(soup: BeautifulSoup, embedded: dict[str, Any]) -> Any:
        value = search(embedded, ("credits", "ects", "credit_points", "credit"))
        if value is None:
            value = label_value(soup, ("Credits", "ECTS", "Credit points"))
        if isinstance(value, str):
            m = re.search(r"\d+(?:\.\d+)?", value)
            if not m:
                return None
            num = float(m.group(0))
            return int(num) if num.is_integer() else num
        return value if isinstance(value, (int, float)) else None

    @staticmethod
    def _location(node: dict[str, Any], soup: BeautifulSoup, embedded: dict[str, Any]) -> str | None:
        addr = node.get("address")
        if isinstance(addr, dict):
            parts = [addr.get(k) for k in ("addressLocality", "addressRegion", "addressCountry")]
            joined = ", ".join(str(p) for p in parts if p)
            if joined:
                return joined
        elif isinstance(addr, str) and addr.strip():
            return addr.strip()
        return as_str(search(embedded, ("campus_location", "location", "city"))) or label_value(
            soup, ("Location", "Campus", "City")
        )

    @staticmethod
    def _scholarships(embedded: dict[str, Any]) -> bool | None:
        value = search(embedded, ("scholarships_available", "scholarship_available", "scholarships_offered"))
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("yes", "true", "available", "offered"):
                return True
            if low in ("no", "false", "none", "not available"):
                return False
        return None

    def _tuition(self, soup: BeautifulSoup, embedded: dict[str, Any]) -> dict[str, dict[str, Any]]:
        empty = {"amount": None, "currency": None, "per": None}
        intl_text = label_value(
            soup,
            ("Tuition fee (international)", "International tuition fee", "Overseas tuition fee",
             "Tuition fee for international students"),
        )
        dom_text = label_value(
            soup,
            ("Tuition fee (home)", "Home tuition fee", "Domestic tuition fee",
             "Tuition fee for home students"),
        )
        plain_text = label_value(soup, ("Tuition fee", "Tuition fees", "Annual tuition", "Program fee", "Course fee"))
        if not intl_text and not dom_text and not plain_text:
            raw = search(embedded, ("tuition", "tuition_fee", "tuitionfee", "annual_tuition", "programme_fee"))
            parsed = parse_money(str(raw)) if raw is not None else None
            if parsed and parsed["amount"] is not None:
                return {
                    "international": parsed if self.default_fee_bucket == "international" else dict(empty),
                    "domestic": parsed if self.default_fee_bucket == "domestic" else dict(empty),
                }
        international = parse_money(intl_text) or (parse_money(plain_text) if self.default_fee_bucket == "international" else None)
        domestic = parse_money(dom_text) or (parse_money(plain_text) if self.default_fee_bucket == "domestic" else None)
        return {"international": international or dict(empty), "domestic": domestic or dict(empty)}


class MastersportalParser(BaseParser):
    domains = ("mastersportal.com",)
    source = "mastersportal"


# --- registry (add a new site: create a class, append it here) -------------
PARSERS: tuple[type[BaseParser], ...] = (
    MastersportalParser,
)


def parser_for(url: str) -> BaseParser:
    host = (urlparse(url).hostname or "").lower()
    for cls in PARSERS:
        if any(host == d or host.endswith("." + d) for d in cls.domains):
            return cls()
    return BaseParser()
