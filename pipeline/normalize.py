"""
Normalize: phones to E.164 (+91 default), dates to YYYY-MM,
skills/languages to lowercase deduped canonical list.
Operates in-place on a CandidateRecord; returns the same object.
"""
import re
from typing import Optional

from models.candidate import CandidateRecord, SkillEntry


# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------

_DIGIT_RE = re.compile(r"\D")


def _normalize_phone(raw: str) -> Optional[str]:
    """
    Normalize a phone number to E.164.
    If no country code is present, assume +91 (India).
    Returns None if the string cannot be parsed into a plausible phone number.
    """
    if not raw:
        return None

    digits = _DIGIT_RE.sub("", raw)
    if not digits:
        return None

    # Remove leading zeros that are trunk prefixes
    has_plus = raw.strip().startswith("+")

    if has_plus:
        # Already has a country code — keep as-is after stripping non-digits
        return f"+{digits}"

    # No explicit country code
    if len(digits) == 10:
        # Assume India mobile (10 digits, no country code)
        return f"+91{digits}"

    if len(digits) == 11 and digits.startswith("0"):
        # Indian trunk prefix 0 + 10 digits
        return f"+91{digits[1:]}"

    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"

    if len(digits) >= 7:
        # Last resort: assume India
        return f"+91{digits}"

    return None


def normalize_phones(phones: list, warnings: Optional[list] = None) -> list:
    seen = set()
    result = []
    for p in phones:
        raw = str(p)
        norm = _normalize_phone(raw)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
        elif not norm and raw.strip():
            if warnings is not None:
                warnings.append(f"Phone '{raw}' could not be normalized to E.164 — dropped")
    return sorted(result)


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    # YYYY-MM  (already canonical)
    (re.compile(r"^(\d{4})-(\d{2})$"), lambda m: f"{m.group(1)}-{m.group(2)}"),
    # YYYY-MM-DD
    (re.compile(r"^(\d{4})-(\d{2})-\d{2}$"), lambda m: f"{m.group(1)}-{m.group(2)}"),
    # MM/YYYY or MM-YYYY
    (re.compile(r"^(\d{1,2})[/-](\d{4})$"), lambda m: f"{m.group(2)}-{m.group(1).zfill(2)}"),
    # YYYY only
    (re.compile(r"^(\d{4})$"), lambda m: f"{m.group(1)}-01"),
    # Month name YYYY  e.g. "Jan 2020"
    (re.compile(r"^([A-Za-z]{3,9})\s+(\d{4})$"), lambda m: _month_name_to_num(m.group(1), m.group(2))),
]

_MONTH_NAMES = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    "january": "01", "february": "02", "march": "03", "april": "04",
    "june": "06", "july": "07", "august": "08", "september": "09",
    "october": "10", "november": "11", "december": "12",
}


def _month_name_to_num(month_str: str, year: str) -> Optional[str]:
    num = _MONTH_NAMES.get(month_str.lower())
    if num:
        return f"{year}-{num}"
    return None


def normalize_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    for pattern, formatter in _DATE_PATTERNS:
        m = pattern.match(raw)
        if m:
            result = formatter(m)
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# Skills normalization
# ---------------------------------------------------------------------------

def normalize_skills(skills: list) -> list:
    """
    Deduplicate and lowercase all skill names.
    Merge SkillEntry objects with the same normalized name, unioning sources.
    Returns sorted list.
    """
    merged: dict[str, SkillEntry] = {}
    for s in skills:
        if isinstance(s, SkillEntry):
            key = s.name.lower().strip()
            if not key:
                continue
            if key in merged:
                existing = merged[key]
                all_sources = list(dict.fromkeys(existing.sources + s.sources))
                merged[key] = SkillEntry(
                    name=key,
                    confidence=max(existing.confidence, s.confidence),
                    sources=all_sources,
                )
            else:
                merged[key] = SkillEntry(name=key, confidence=s.confidence, sources=list(s.sources))
        elif isinstance(s, str):
            key = s.lower().strip()
            if key and key not in merged:
                merged[key] = SkillEntry(name=key, sources=[])
    return [merged[k] for k in sorted(merged.keys())]


# ---------------------------------------------------------------------------
# Email normalization
# ---------------------------------------------------------------------------

def normalize_emails(emails: list) -> list:
    seen = set()
    result = []
    for e in emails:
        norm = str(e).lower().strip()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return sorted(result)


# ---------------------------------------------------------------------------
# Full record normalizer
# ---------------------------------------------------------------------------

def normalize_record(rec: CandidateRecord, warnings: Optional[list] = None) -> CandidateRecord:
    rec.phones = normalize_phones(rec.phones, warnings)
    rec.emails = normalize_emails(rec.emails)
    rec.skills = normalize_skills(rec.skills)

    for exp in rec.experience:
        exp.start = normalize_date(exp.start)
        exp.end = normalize_date(exp.end)

    for edu in rec.education:
        if edu.end_year and not isinstance(edu.end_year, int):
            try:
                edu.end_year = int(str(edu.end_year)[:4])
            except (ValueError, TypeError):
                edu.end_year = None

    if rec.headline:
        rec.headline = rec.headline.strip() or None

    if rec.full_name:
        rec.full_name = " ".join(rec.full_name.split())  # collapse whitespace

    return rec
