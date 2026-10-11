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
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

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
    """Find 'IELTS 7' / 'Duolingo English Test 130' style requirement pairs.

    Scores are sanity-capped at 200 so page-wide scans can't invent
    nonsense like 'TOEFL: 10000' (never guess)."""
    found: dict[str, str] = {}

    def keep(test: str, score: str) -> None:
        try:
            if float(score) > 200:
                return
        except ValueError:
            return
        found.setdefault(test.lower(), {"test": test, "min_score": score})

    for m in _TEST_BEFORE.finditer(html_text):
        keep(" ".join(m.group(1).split()), m.group(2))
    for m in _TEST_AFTER.finditer(html_text):
        keep(" ".join(m.group(2).split()), m.group(1))
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
_ORG_TYPES = {
    "organization", "educationalorganization", "collegeoruniversity",
    "corporation", "localbusiness", "ngo", "governmentorganization",
}


def official_website_url(soup: BeautifulSoup) -> str | None:
    """'Visit University Website' button -> real URL lives in data-description."""
    anchor = soup.find("a", title=re.compile(r"Visit University Website", re.I)) or soup.find(
        "a", class_=re.compile(r"UniversityWebsiteLink")
    )
    if not anchor:
        return None
    real = anchor.get("data-description") or anchor.get("href")
    if not real:
        return None
    netloc = urlparse(real).netloc.lower()
    if not netloc or "prtl.co" in netloc or "studyportals" in netloc:
        return None  # tracking redirect without a visible target
    return strip_tracking(real)


def scholarships_from_html(html: str, url: str) -> bool | None:
    """True when the page links its OWN scholarship items/section; None = no data.
    Requiring the page's own slug ignores site-wide nav links (never guess)."""
    slug = urlparse(url).path.rsplit("/", 1)[-1].lower()
    for suffix in (".html", ".php", "/"):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
    if slug and re.search(rf'/scholarships/[^"\']*{re.escape(slug)}', html, re.I):
        return True
    if re.search(r'#?["\']?ScholarshipsAndFunding', html, re.I):
        return True
    return None


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


def entity_urls(jsonld: list[dict[str, Any]]) -> list[str]:
    """Entity links of a listing page (JSON-LD mainEntity / itemListElement)."""
    urls: list[str] = []
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
            link = as_str(item.get("url"))
            if link:
                urls.append(link)
    return urls


def discover(html: str, base_url: str) -> tuple[bool, list[str]]:
    """Is this a listing page, and which same-host entity URLs does it list?"""
    soup = BeautifulSoup(html, "html.parser")
    jsonld = jsonld_objects(soup)
    if not is_listing_page(jsonld):
        return False, []
    host = urlparse(base_url).netloc
    urls = [u for u in dict.fromkeys(entity_urls(jsonld)) if urlparse(u).netloc == host]
    return True, urls


_STUDIES_HREF_RE = re.compile(r"""href=["']([^"']*?/studies/\d+/[^"']*)["']""", re.I)


def program_links(html: str, base_url: str) -> list[str]:
    """Program URLs linked from a university profile page (/universities/...).

    Harvested ONLY from university pages: program pages link 'similar programs',
    which would balloon the crawl beyond the university's own catalogue."""
    if not urlparse(base_url).path.startswith("/universities/"):
        return []
    host = urlparse(base_url).netloc
    found: list[str] = []
    for m in _STUDIES_HREF_RE.finditer(html):
        link = urljoin(base_url, m.group(1).replace("&amp;", "&"))
        if urlparse(link).netloc == host:
            found.append(strip_tracking(link))
    return list(dict.fromkeys(found))


def strip_tracking(url: str) -> str:
    """Drop utm_*/gclid/fbclid query params and fragments from an official link."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "gclid", "fbclid"))
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query) if query else "", ""))


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


# --- program page structured extraction (mastersportal quick facts etc.) ---

JUNK_VALUES = {"unknown", "not specified", "n/a", "na", "none", "null", "-", "--", "tba", "not available", "no data"}
_MODE_WORDS = ("on campus", "on-campus", "online", "blended", "hybrid", "on site", "on-site", "distance")


def no_junk(value: Any) -> str | None:
    """Clean a text value; 'Unknown'/'Not specified'/... -> None (never guess)."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.replace("\xa0", " ").split())
    if not text or text.lower().rstrip(":") in JUNK_VALUES:
        return None
    return text


def hero_chips(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """(degree_type, delivered) from the header chips: 'Postgraduate Certificate', 'On Campus'."""
    degree: str | None = None
    delivered: str | None = None
    for chip in soup.find_all(class_="StudyInformationChip"):
        text = no_junk(chip.get_text(" ", strip=True))
        if not text:
            continue
        low = text.lower()
        if any(w in low for w in _MODE_WORDS):
            delivered = delivered or norm_mode(text)
        elif degree is None:
            degree = text
    return degree, delivered


def quick_facts(soup: BeautifulSoup) -> dict[str, dict[str, Any]]:
    """Parse QuickFactComponent blocks -> {"start date": {"text":..., "times":[...]}, ...}.
    Row/Column duplicates are merged; 'Unknown' values are dropped."""
    facts: dict[str, dict[str, Any]] = {}
    for comp in soup.find_all(class_=re.compile(r"QuickFactComponent")):
        label_el = comp.find(class_="Label") or comp.find(class_="QuickFactType")
        if not label_el:
            continue
        label = no_junk(label_el.get_text(" ", strip=True))
        if not label:
            continue
        label = label.lower()
        value_el = comp.find(class_="Value") or comp.find(class_="ValueContainer") or comp.find(class_="QuickFactData")
        text: str | None = None
        times: list[str] = []
        if value_el:
            clone = BeautifulSoup(str(value_el), "html.parser")
            times = [t.get("datetime", "") for t in clone.find_all("time", datetime=True)]
            for bad in clone.find_all(class_="js-notAvailable"):
                bad.decompose()
            text = no_junk(clone.get_text(" ", strip=True))
        if label in facts:
            facts[label]["text"] = facts[label]["text"] or text
            facts[label]["times"] = list(dict.fromkeys(facts[label]["times"] + times))
        else:
            facts[label] = {"text": text, "times": times}
    return facts


def month_year(value: Any, prefix: str = "") -> str | None:
    """'2027-09-22 00:00:00' -> 'September 2027' (or 'Before July 2027' with prefix)."""
    m = re.match(r"(\d{4})-(\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return f"{prefix}{datetime(int(m.group(1)), int(m.group(2)), 1):%B %Y}"
    except ValueError:
        return None


def _clean_test_name(text: str) -> str | None:
    """'TOEFL ®' -> 'TOEFL' (trademark glyphs are noise, never data)."""
    return no_junk(re.sub(r"[®™©]", " ", text))


def _dedupe_seq(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def extract_dates(soup: BeautifulSoup, jsonld: list[dict[str, Any]], facts: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    """start_date / apply_date from <time datetime> facts, deadline list, JSON-LD instances."""
    starts: list[str] = []
    applies: list[str] = []
    for key in ("start date", "start", "intake", "intakes", "starting"):
        for t in facts.get(key, {}).get("times", []):
            starts.append(month_year(t))
    for key in ("apply date", "application deadline", "deadline", "apply by", "application closing date"):
        for t in facts.get(key, {}).get("times", []):
            applies.append(month_year(t, prefix="Before "))
    for t in soup.select(".StartDateItemTime time[datetime]"):
        starts.append(month_year(t.get("datetime")))
    for t in soup.select("li.ApplicationDeadline time[datetime], .DeadlinesList time[datetime]"):
        applies.append(month_year(t.get("datetime"), prefix="Before "))
    for node in jsonld:
        for inst in node.get("hasCourseInstance") or []:
            if isinstance(inst, dict):
                starts.append(month_year(inst.get("startDate")))
    # label fallback (junk-filtered)
    if not starts:
        raw = facts.get("start date", {}).get("text") or label_value(
            soup, ("Start date", "Start dates", "Intake", "Intakes", "Application start")
        )
        starts.extend(to_list(no_junk(raw)))
    if not applies:
        raw = facts.get("apply date", {}).get("text") or label_value(
            soup, ("Application deadline", "Application deadlines", "Apply by", "Deadline", "Apply date")
        )
        applies.extend(to_list(no_junk(raw)))
    return _dedupe_seq([s for s in starts if s]), _dedupe_seq([a for a in applies if a])


def tuition_from_page(soup: BeautifulSoup) -> dict[str, dict[str, Any]] | None:
    """Structured fee boxes: <div class="TuitionFeeContainer" data-target="international|national">.

    Mastersportal may rewrite the shown number into a local currency
    (data-amount), while data-original-amount / data-original_html keep the
    real fee in the institution's own currency -- always record the real one."""
    found: dict[str, dict[str, Any]] = {}
    for cont in soup.select(".TuitionFeeContainer[data-target]"):
        if "js-notAvailable" in (cont.get("class") or []):
            continue
        # fees of pathway / alternative-provider cards are not this programme's fee
        if cont.find_parent(class_=re.compile(r"Pathway|OrganisationInformation|AdditionalProvider")):
            continue
        target = cont.get("data-target")
        bucket = ("international" if target in ("international", "overseas") else
                  "domestic" if target in ("national", "domestic", "home", "eu") else None)
        if bucket is None or bucket in found:
            continue  # first box in the page order is the programme's own fee
        amount_el = cont.find(attrs={"data-amount": True})
        if not amount_el:
            continue
        raw_amount = amount_el.get("data-original-amount") or amount_el.get("data-amount")
        try:
            num = float(raw_amount)
            amount: int | float = int(num) if num.is_integer() else num
        except (TypeError, ValueError):
            continue
        cur_el = cont.find(attrs={"data-currency-text": True})
        shown_currency = (cur_el.get("data-currency-text") if cur_el else None) or amount_el.get("data-currency")
        institution_currency = cur_el.get("data-institution-currency") if cur_el else None
        original_html = amount_el.get("data-original_html") or ""
        m_orig = re.search(r"\b([A-Z]{3})\b", original_html)
        currency = (m_orig.group(1) if m_orig else None) or institution_currency or shown_currency
        note = None
        if not amount_el.get("data-original-amount") and institution_currency and shown_currency and shown_currency != institution_currency:
            # no original value on the page -> only the rewritten (converted) number exists
            note = "Mastersportal-এর দেখানো রূপান্তরিত মান, আসল মুদ্রা নয়"
        unit_el = cont.find(class_="Unit")
        unit_text = unit_el.get_text(" ", strip=True).lower() if unit_el else ""
        if re.search(r"\b(full|programme|program|course|degree|total)\b", unit_text):
            per = "total"  # one fee for the whole programme, not a yearly rate
        elif "yr" in unit_text or "year" in unit_text:
            per = "year"
        elif "month" in unit_text or "/ mo" in unit_text:
            per = "month"
        else:
            per = None
        if per is None:  # no visible unit -> read it from the box text / amount coverage
            box_text = cont.get_text(" ", strip=True).lower()
            m_unit = re.search(r"/\s*(yr|year|month)s?\b", box_text)
            if m_unit:
                per = "year" if m_unit.group(1).startswith("yr") or m_unit.group(1) == "year" else "month"
        if per is None:
            dur, period = amount_el.get("data-duration"), (amount_el.get("data-period") or "").lower()
            try:
                if period.startswith("year"):
                    per = "year"
                elif period.startswith("month") and dur is not None:
                    per = "year" if float(dur) >= 12 else "month"
            except ValueError:
                pass
        if bucket == "international":
            found["international"] = {"amount": amount, "currency": currency, "per": per, "note": note}
        else:
            found["domestic"] = {"amount": amount, "currency": currency, "per": per}
    if found:
        empty_intl = {"amount": None, "currency": None, "per": None, "note": None}
        empty_dom = {"amount": None, "currency": None, "per": None}
        return {"international": found.get("international") or empty_intl, "domestic": found.get("domestic") or empty_dom}
    return None


def language_cards(soup: BeautifulSoup) -> list[dict[str, str]]:
    """EnglishRequirementsCards -> [{'test': 'IELTS', 'min_score': '7'}, ...]."""
    out: list[dict[str, str]] = []
    for card in soup.select(".CardContents[data-cy^='card-']"):
        heading = card.find(class_="Heading")
        if not heading:
            continue
        test = _clean_test_name(heading.get_text(" ", strip=True))
        if not test:
            continue
        score_el = card.find(class_="Score")
        score = no_junk(score_el.get_text(" ", strip=True)) if score_el else None
        out.append({"test": test, "min_score": score})
    if out:
        seen: set[tuple[str, str]] = set()
        return [c for c in out if not ((k := (c["test"].lower(), str(c["min_score"]))) in seen or seen.add(k))]
    # fallback: scope the text scan to the language section only (never the whole page)
    section = soup.find("article", class_="LanguageFact") or soup.find(
        class_=re.compile(r"englishRequirements", re.I)
    )
    return language_tests(section.get_text(" ", strip=True)) if section else []


def duration_from_facts(soup: BeautifulSoup, facts: dict[str, dict[str, Any]]) -> dict[str, str | None]:
    entry = facts.get("duration") or {}
    text = entry.get("text")
    el = soup.find(class_="js-duration")
    if el and el.get("data-duration") and el.get("data-period"):
        text = f"{el['data-duration']} {el['data-period']}"
    full = norm_duration(text)
    part = norm_duration(facts.get("part time duration", {}).get("text"))
    if full or part:
        return {"full_time": full, "part_time": part}
    return {}


def living_costs_from_page(soup: BeautifulSoup) -> dict[str, Any] | None:
    """#CostOfLivingContainer: 697-1093 GBP / month -> amount '697 - 1093'."""
    container = soup.select_one("#CostOfLivingContainer .Costs") or soup.find(class_="CostsOfLiving")
    if not container:
        return None
    amounts: list[int | float] = []
    for el in container.find_all(attrs={"data-amount": True}):
        try:
            num = float(el["data-amount"])
            amounts.append(int(num) if num.is_integer() else num)
        except (TypeError, ValueError):
            continue
    if not amounts:
        return None
    cur_el = container.find(attrs={"data-currency-text": True})
    unit_text = container.get_text(" ", strip=True).lower()
    per = "month" if ("/ month" in unit_text or "monthly" in unit_text) else (
        "year" if ("/ year" in unit_text or "annually" in unit_text) else None
    )
    amount: Any = amounts[0] if len(amounts) == 1 else f"{min(amounts)} - {max(amounts)}"
    return {"amount": amount, "currency": cur_el.get("data-currency-text") if cur_el else None, "per": per}


def field_of_study_from_breadcrumbs(jsonld: list[dict[str, Any]]) -> str | None:
    """BreadcrumbList: ['All studies', '<subject>', ...] -> subject."""
    for node in jsonld:
        if node.get("@type") != "BreadcrumbList":
            continue
        names: list[str] = []
        for item in node.get("itemListElement") or []:
            if not isinstance(item, dict):
                continue
            inner = item.get("item") if isinstance(item.get("item"), dict) else {}
            name = as_str(inner.get("name") or item.get("name") or inner.get("title"))
            if name:
                names.append(name)
        if names and names[0].lower() == "all studies" and len(names) > 1:
            return names[1]
    return None


def pick_program_name(
    soup: BeautifulSoup, node: dict[str, Any], degree: str | None, embedded: dict[str, Any]
) -> str | None:
    """Program name by trying alternative sources in order (never guesses)."""
    hero = soup.find(class_="StudyName") or soup.find("h1", class_=re.compile(r"HeroTitle")) or soup.h1
    if hero is not None:
        anchor = hero.find("a", title=True)
        candidate = no_junk(anchor.get("title") if anchor else hero.get_text(" ", strip=True))
        if candidate:
            return candidate
    og = no_junk(meta_content(soup, "og:title"))
    if og:
        og = re.split(r"\s+[|–—]\s+", og)[0]
        if not (degree and degree.lower() in og.lower()):
            return og
    name = as_str(node.get("name"))
    if name and degree and name.lower().endswith(", " + degree.lower()):
        name = name[: -(len(degree) + 2)].strip()  # 'English with SEND, Postgraduate Certificate'
    if name:
        return no_junk(name)
    title = no_junk(soup.title.get_text(strip=True) if soup.title else None)
    if title:
        title = re.split(r"\s+[|–—]\s+", title)[0].strip()
        if degree and degree.lower() in title.lower():
            title = title.split(degree, 1)[0].strip(" ,|-")
        title = title.split(" at ", 1)[0].strip()
        if title:
            return no_junk(title)
    return no_junk(as_str(search(embedded, ("program_name", "course_name", "study_name", "program_title"))))


def programme_website(soup: BeautifulSoup) -> str | None:
    """'Visit Programme Website' hero link -> real URL in data-description."""
    anchor = soup.find("a", class_=re.compile(r"ProgrammeWebsiteLink|ProgramWebsiteLink")) or soup.find(
        "a", title=re.compile(r"Visit Programme Website", re.I)
    )
    if not anchor:
        return None
    real = anchor.get("data-description") or anchor.get("href")
    if not real:
        return None
    netloc = urlparse(real).netloc.lower()
    if not netloc or "prtl.co" in netloc or "studyportals" in netloc:
        return None
    return strip_tracking(real)


def about_text(soup: BeautifulSoup) -> str | None:
    """'About' section paragraphs (richer than the meta description)."""
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if not re.fullmatch(r"about[:\s]*", heading.get_text(" ", strip=True), re.I):
            continue
        parts: list[str] = []
        for sib in heading.find_all_next():
            if sib is heading:
                continue
            if sib.name in ("h2", "h3", "h4"):
                break
            if sib.name == "p":
                text = no_junk(sib.get_text(" ", strip=True))
                if text:
                    parts.append(text)
                if sum(len(p) for p in parts) > 1500:
                    break
        if parts:
            return " ".join(parts)
    return None


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
        is_org = bool(_types(node) & _ORG_TYPES)
        page_host = urlparse(url).netloc
        title_name, title_org = clean_title(soup.title.get_text(strip=True) if soup.title else None)
        h1 = soup.h1.get_text(" ", strip=True) if soup.h1 else None
        site_name = meta_content(soup, "og:site_name")

        record["overview"] = (
            as_str(node.get("description")) or meta_content(soup, "description", "og:description")
        )

        # --- university/organisation profile page ---------------------------
        # Program-specific fields stay null: they don't exist for a university.
        if is_org:
            record["program_name"] = None
            record["university"] = as_str(node.get("name")) or h1
            record["campus_location"] = self._location(node, soup, embedded)
            record["official_program_url"] = official_website_url(soup)
            record["scholarships_available"] = scholarships_from_html(html, url)
            return

        # --- program page: names / links -------------------------------------
        facts = quick_facts(soup)
        degree_chip, mode_chip = hero_chips(soup)
        record["program_name"] = pick_program_name(soup, node, degree_chip, embedded)
        if title_org and site_name and title_org.lower() == site_name.lower():
            title_org = None  # 'Mastersportal' is the publisher, not a university
        record["university"] = (
            as_str(node.get("provider")) or as_str(node.get("organizer"))
            or as_str(search(embedded, ("university", "institution", "organisation_name", "organization_name")))
            or title_org or h1
        )
        record["official_program_url"] = programme_website(soup) or self._official_url(
            node, soup, embedded, url, page_host
        )
        record["overview"] = about_text(soup) or record["overview"]

        # degree / field / mode / duration
        record["degree_type"] = degree_chip or (
            as_str(node.get("educationalCredentialAwarded")) or as_str(node.get("credentialAwarded"))
            or as_str(search(embedded, ("degree_type", "qualification", "credential_award")))
            or no_junk(label_value(soup, ("Degree", "Award", "Qualification", "Credential")))
        )
        record["field_of_study"] = (
            field_of_study_from_breadcrumbs(jsonld)
            or as_str(node.get("about"))
            or as_str(search(embedded, ("field_of_study", "subject_area", "discipline")))
        )
        record["delivered"] = mode_chip or norm_mode(
            label_value(soup, ("Study mode", "Mode of study", "Delivery mode", "Mode of delivery", "Attendance"))
            or search(embedded, ("delivery_mode", "study_mode", "mode_of_study", "attendance"))
        )
        record["duration"] = duration_from_facts(soup, facts) or self._duration(soup, embedded, node)
        record["credits"] = self._credits(soup, embedded)

        # dates / place / language
        starts, applies = extract_dates(soup, jsonld, facts)
        record["start_date"] = starts or to_list(
            search(embedded, ("start_date", "startdate", "intake", "intakes"))
        )
        record["apply_date"] = applies or to_list(
            search(embedded, ("apply_date", "application_deadline", "deadline"))
        )
        record["campus_location"] = no_junk(facts.get("campus location", {}).get("text")) or self._location(
            node, soup, embedded
        )
        taught_in = no_junk(facts.get("taught in", {}).get("text")) or no_junk(
            (soup.find(class_="Languages") or {}).get_text(" ", strip=True)
        )
        record["language"]["taught_in"] = taught_in or (
            as_str(node.get("inLanguage"))
            or no_junk(label_value(soup, ("Language of instruction", "Taught in", "Teaching language")))
            or as_str(search(embedded, ("language_of_instruction", "taught_in", "teaching_language")))
        )
        record["language"]["requirements"] = language_cards(soup) or [
            {"test": t, "min_score": s} for t, s in (
                (as_str(search(embedded, (f"{name}_test",))) , as_str(search(embedded, (f"{name}_score",))))
                for name in ("ielts", "toefl", "pte")
            ) if t
        ]

        # money / requirements
        record["tuition_fee"] = tuition_from_page(soup) or self._tuition(soup, embedded)
        record["living_costs"] = (
            living_costs_from_page(soup)
            or parse_money(label_value(soup, ("Living cost", "Living costs", "Estimated living costs", "Cost of living")))
            or {"amount": None, "currency": None, "per": None}
        )
        gpa = no_junk(label_value(soup, ("GPA", "Minimum GPA", "GPA requirement"))) or as_str(
            search(embedded, ("gpa", "minimum_gpa", "gpa_requirement"))
        )
        record["academic_requirements"]["gpa"] = gpa
        record["scholarships_available"] = self._scholarships(embedded)
        if record["scholarships_available"] is None:
            record["scholarships_available"] = scholarships_from_html(html, url)

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
        # JSON-LD: Organization.address or Organization.location.address (PostalAddress)
        addr = node.get("address")
        if not isinstance(addr, dict):
            loc = node.get("location")
            if isinstance(loc, dict):
                addr = loc.get("address") if isinstance(loc.get("address"), dict) else loc
        if isinstance(addr, dict):
            parts = [as_str(addr.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")]
            joined = ", ".join(p for p in parts if p)
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
        intl_empty = {"amount": None, "currency": None, "per": None, "note": None}
        dom_empty = {"amount": None, "currency": None, "per": None}

        def intl(parsed: dict[str, Any] | None) -> dict[str, Any]:
            return {**intl_empty, **parsed} if parsed else dict(intl_empty)

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
                    "international": intl(parsed) if self.default_fee_bucket == "international" else dict(intl_empty),
                    "domestic": parsed if self.default_fee_bucket == "domestic" else dict(dom_empty),
                }
        international = intl(
            parse_money(intl_text) or (parse_money(plain_text) if self.default_fee_bucket == "international" else None)
        )
        domestic = parse_money(dom_text) or (parse_money(plain_text) if self.default_fee_bucket == "domestic" else None) or dict(dom_empty)
        return {"international": international, "domestic": domestic}


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
