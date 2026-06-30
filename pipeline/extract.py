"""
Extract: parse each raw source into a list of CandidateRecord objects.
Never raises on bad data — logs a warning and returns what it can.
"""
import csv
import json
import re
import sys
from typing import Optional
from urllib.parse import urlparse

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from models.candidate import (
    CandidateRecord, ProvenanceEntry, SkillEntry,
    LinksEntry, LocationEntry, ExperienceEntry,
)

GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# CSV extractor
# ---------------------------------------------------------------------------

def extract_csv(path: str, warnings: list) -> list:
    """Parse CSV with columns: name, email, phone, current_company, title."""
    records = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                row = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items()}
                rec = CandidateRecord(source="csv", raw=dict(row))

                name = row.get("name") or row.get("full_name") or ""
                email = row.get("email") or row.get("email_address") or ""
                phone = row.get("phone") or row.get("phone_number") or ""
                company = row.get("current_company") or row.get("company") or ""
                title = row.get("title") or row.get("job_title") or ""

                rec.full_name = name or None
                if email:
                    rec.emails = [email.lower()]
                if phone:
                    rec.phones = [phone]
                if company or title:
                    rec.experience = [
                        ExperienceEntry(company=company or None, title=title or None)
                    ]
                    if title:
                        rec.headline = title

                prov = []
                if name:
                    prov.append(ProvenanceEntry("full_name", "csv", "direct"))
                if email:
                    prov.append(ProvenanceEntry("emails", "csv", "direct"))
                if phone:
                    prov.append(ProvenanceEntry("phones", "csv", "direct"))
                if title:
                    prov.append(ProvenanceEntry("headline", "csv", "direct"))
                if company or title:
                    prov.append(ProvenanceEntry("experience", "csv", "direct"))
                rec.provenance = prov

                records.append(rec)

    except FileNotFoundError:
        warnings.append(f"CSV file not found: {path}")
    except Exception as exc:
        warnings.append(f"CSV parse error ({path}): {exc}")

    return records


# ---------------------------------------------------------------------------
# ATS JSON extractor  (field names differ from canonical)
# ---------------------------------------------------------------------------

ATS_FIELD_MAP = {
    # ATS field name       -> canonical field
    "candidate_name":       "full_name",
    "contact_email":        "emails",
    "email":                "emails",
    "phone_number":         "phones",
    "phone":                "phones",
    "employer":             "company",     # -> experience[0].company
    "current_employer":     "company",
    "role":                 "title",       # -> experience[0].title
    "job_title":            "title",
    "current_role":         "title",
    "location":             "location_raw",
    "city":                 "city",
    "country":              "country",
    "linkedin_url":         "linkedin",
    "github_url":           "github",
    "summary":              "headline",
    "bio":                  "headline",
    "skills":               "skills",
    "tags":                 "skills",
    "experience_years":     "years_experience",
    "years_of_experience":  "years_experience",
    "start_date":           "exp_start",
    "join_date":            "exp_start",
    "end_date":             "exp_end",
    "leaving_date":         "exp_end",
}


def _map_ats_record(raw: dict, warnings: list) -> CandidateRecord:
    rec = CandidateRecord(source="ats", raw=raw)
    mapped = {}
    for k, v in raw.items():
        canonical_key = ATS_FIELD_MAP.get(k.lower().strip())
        if canonical_key and v not in (None, "", []):
            mapped[canonical_key] = v

    rec.full_name = mapped.get("full_name") or None

    email_val = mapped.get("emails")
    if isinstance(email_val, str) and email_val:
        rec.emails = [email_val.lower()]
    elif isinstance(email_val, list):
        rec.emails = [e.lower() for e in email_val if e]

    phone_val = mapped.get("phones")
    if isinstance(phone_val, str) and phone_val:
        rec.phones = [phone_val]
    elif isinstance(phone_val, list):
        rec.phones = [p for p in phone_val if p]

    company = mapped.get("company")
    title = mapped.get("title")
    if company or title:
        rec.experience = [ExperienceEntry(
            company=company or None,
            title=title or None,
            start=mapped.get("exp_start") or None,
            end=mapped.get("exp_end") or None,
        )]
    if title:
        rec.headline = mapped.get("headline") or title
    if mapped.get("headline"):
        rec.headline = mapped["headline"]

    yoe = mapped.get("years_experience")
    if yoe is not None:
        try:
            rec.years_experience = float(yoe)
        except (ValueError, TypeError):
            pass

    skills_raw = mapped.get("skills")
    if skills_raw:
        if isinstance(skills_raw, str):
            skills_raw = [s.strip() for s in re.split(r"[,;|]", skills_raw) if s.strip()]
        if isinstance(skills_raw, list):
            rec.skills = [SkillEntry(name=str(s).strip().lower(), sources=["ats"]) for s in skills_raw if s]

    loc_raw = mapped.get("location_raw")
    city = mapped.get("city")
    country = mapped.get("country")
    if loc_raw or city or country:
        rec.location = LocationEntry(city=city or loc_raw, country=country)

    linkedin = mapped.get("linkedin")
    github = mapped.get("github")
    if linkedin or github:
        rec.links = LinksEntry(linkedin=linkedin, github=github)

    prov = []
    if rec.full_name:
        prov.append(ProvenanceEntry("full_name", "ats", "mapped"))
    if rec.emails:
        prov.append(ProvenanceEntry("emails", "ats", "mapped"))
    if rec.phones:
        prov.append(ProvenanceEntry("phones", "ats", "mapped"))
    if rec.headline:
        prov.append(ProvenanceEntry("headline", "ats", "mapped"))
    if rec.experience:
        prov.append(ProvenanceEntry("experience", "ats", "mapped"))
    if rec.skills:
        prov.append(ProvenanceEntry("skills", "ats", "mapped"))
    if rec.years_experience is not None:
        prov.append(ProvenanceEntry("years_experience", "ats", "mapped"))
    rec.provenance = prov
    return rec


def extract_ats(path: str, warnings: list) -> list:
    """Parse ATS JSON file — supports a single object or an array of objects."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        warnings.append(f"ATS file not found: {path}")
        return []
    except json.JSONDecodeError as exc:
        warnings.append(f"ATS JSON parse error ({path}): {exc}")
        return []

    if isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        warnings.append(f"ATS file ({path}): expected object or array, got {type(data).__name__}")
        return []

    records = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            warnings.append(f"ATS record #{i} is not an object, skipping")
            continue
        try:
            records.append(_map_ats_record(item, warnings))
        except Exception as exc:
            warnings.append(f"ATS record #{i} mapping error: {exc}")
    return records


# ---------------------------------------------------------------------------
# GitHub extractor
# ---------------------------------------------------------------------------

def _parse_github_username(username_or_url: str) -> Optional[str]:
    s = username_or_url.strip()
    if "/" in s:
        parsed = urlparse(s if "://" in s else "https://" + s)
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            return parts[0]
        return None
    return s


def _gh_get(url: str, warnings: list) -> Optional[dict]:
    if not HAS_REQUESTS:
        warnings.append("requests library not installed; GitHub source skipped")
        return None
    try:
        resp = requests.get(url, headers={"Accept": "application/vnd.github.v3+json"}, timeout=10)
        if resp.status_code == 404:
            warnings.append(f"GitHub API 404 for {url}")
            return None
        if resp.status_code == 403:
            warnings.append(f"GitHub API rate limit or auth error for {url}")
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        warnings.append(f"GitHub API timeout for {url}")
        return None
    except Exception as exc:
        warnings.append(f"GitHub API error for {url}: {exc}")
        return None


def extract_github(username_or_url: str, warnings: list) -> list:
    """Call GitHub REST API and build a CandidateRecord from profile + repos."""
    username = _parse_github_username(username_or_url)
    if not username:
        warnings.append(f"Cannot parse GitHub username from: {username_or_url}")
        return []

    profile = _gh_get(f"{GITHUB_API}/users/{username}", warnings)
    if not profile:
        return []

    repos_data = _gh_get(f"{GITHUB_API}/users/{username}/repos?per_page=100&sort=updated", warnings)
    repos_data = repos_data if isinstance(repos_data, list) else []

    # Collect languages across repos (language field is the primary language)
    lang_set = set()
    for repo in repos_data:
        lang = repo.get("language")
        if lang:
            lang_set.add(lang.lower())

    rec = CandidateRecord(source="github", raw=profile)

    name = profile.get("name") or profile.get("login") or None
    rec.full_name = name

    email = profile.get("email")
    if email:
        rec.emails = [email.lower()]

    blog = profile.get("blog") or ""
    rec.links = LinksEntry(
        github=f"https://github.com/{username}",
        portfolio=blog if blog else None,
    )

    bio = profile.get("bio")
    if bio:
        rec.headline = bio.strip()

    location_raw = profile.get("location")
    if location_raw:
        parts = [p.strip() for p in location_raw.split(",")]
        city = parts[0] if parts else None
        region = parts[1] if len(parts) > 1 else None
        country = parts[-1] if len(parts) > 2 else (parts[1] if len(parts) == 2 else None)
        rec.location = LocationEntry(city=city, region=region, country=country)

    if lang_set:
        rec.skills = [
            SkillEntry(name=lang, sources=["github"])
            for lang in sorted(lang_set)
        ]

    public_repos = profile.get("public_repos", 0)

    prov = []
    if rec.full_name:
        prov.append(ProvenanceEntry("full_name", "github", "api"))
    if rec.emails:
        prov.append(ProvenanceEntry("emails", "github", "api"))
    if rec.headline:
        prov.append(ProvenanceEntry("headline", "github", "api"))
    if rec.location:
        prov.append(ProvenanceEntry("location", "github", "api"))
    if rec.skills:
        prov.append(ProvenanceEntry("skills", "github", "api"))
    if rec.links:
        prov.append(ProvenanceEntry("links", "github", "api"))
    rec.provenance = prov

    return [rec]
