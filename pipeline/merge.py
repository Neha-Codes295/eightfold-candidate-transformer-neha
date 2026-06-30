"""
Merge: group CandidateRecords by email (primary) or normalized full name (fallback),
then collapse each group into one canonical output dict.

Source priority for scalar conflicts: CSV > ATS > GitHub
Skills/headline: union/merge across all sources.
"""
from typing import Optional
from models.candidate import (
    CandidateRecord, SkillEntry, ProvenanceEntry,
    ExperienceEntry, EducationEntry, LocationEntry, LinksEntry,
)
from pipeline.normalize import normalize_skills

SOURCE_PRIORITY = {"csv": 0, "ats": 1, "github": 2}


def _norm_name_key(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return " ".join(name.lower().split())


def _group_records(records: list) -> list:
    """
    Group CandidateRecords that refer to the same person.
    Primary key: email (any email match within the record's email list).
    Fallback key: normalized full name.
    Returns list of groups (each group is a list of CandidateRecord).
    """
    email_to_group: dict[str, int] = {}
    name_to_group: dict[str, int] = {}
    groups: list[list] = []

    for rec in records:
        matched_group = None

        # Try email match
        for email in rec.emails:
            if email in email_to_group:
                matched_group = email_to_group[email]
                break

        # Try name match if no email hit
        if matched_group is None:
            nk = _norm_name_key(rec.full_name)
            if nk and nk in name_to_group:
                matched_group = name_to_group[nk]

        if matched_group is None:
            matched_group = len(groups)
            groups.append([])

        groups[matched_group].append(rec)

        # Register all emails and name into lookup
        for email in rec.emails:
            email_to_group[email] = matched_group
        nk = _norm_name_key(rec.full_name)
        if nk:
            name_to_group[nk] = matched_group

    return groups


def _pick_scalar(field: str, records: list) -> tuple:
    """
    Pick best value for a scalar field across records using source priority.
    Returns (value, source) tuple. Returns (None, None) if all sources are null.
    """
    candidates = []
    for rec in records:
        val = getattr(rec, field, None)
        if val is not None and val != "" and val != []:
            candidates.append((val, rec.source))

    if not candidates:
        return (None, None)

    # Sort by source priority (lower = higher priority)
    candidates.sort(key=lambda x: SOURCE_PRIORITY.get(x[1], 99))
    return candidates[0]


def _merge_emails(records: list) -> list:
    seen = set()
    result = []
    # Prefer CSV order, then ATS, then GitHub
    for src in ("csv", "ats", "github"):
        for rec in records:
            if rec.source == src:
                for e in rec.emails:
                    if e not in seen:
                        seen.add(e)
                        result.append(e)
    return sorted(result)


def _merge_phones(records: list) -> list:
    seen = set()
    result = []
    for src in ("csv", "ats", "github"):
        for rec in records:
            if rec.source == src:
                for p in rec.phones:
                    if p not in seen:
                        seen.add(p)
                        result.append(p)
    return sorted(result)


def _merge_skills(records: list) -> list:
    """Union skills from all sources, accumulating per-skill source lists."""
    all_skills: dict[str, SkillEntry] = {}
    for rec in records:
        for skill in rec.skills:
            key = skill.name.lower().strip()
            if key not in all_skills:
                all_skills[key] = SkillEntry(name=key, sources=list(skill.sources))
            else:
                for s in skill.sources:
                    if s not in all_skills[key].sources:
                        all_skills[key].sources.append(s)
    return normalize_skills(list(all_skills.values()))


def _merge_experience(records: list) -> list:
    """
    Merge experience lists. Deduplicate by (company, title).
    Higher-priority source wins for scalar conflicts, but lower-priority sources
    fill in gaps (null fields like start/end) that the higher-priority source lacks.
    """
    seen: dict[tuple, ExperienceEntry] = {}
    order = []
    for src in ("csv", "ats", "github"):
        for rec in records:
            if rec.source == src:
                for exp in rec.experience:
                    key = (
                        (exp.company or "").lower().strip(),
                        (exp.title or "").lower().strip(),
                    )
                    if key not in seen:
                        seen[key] = ExperienceEntry(
                            company=exp.company,
                            title=exp.title,
                            start=exp.start,
                            end=exp.end,
                            summary=exp.summary,
                        )
                        order.append(key)
                    else:
                        # Fill null fields from lower-priority source
                        existing = seen[key]
                        if existing.start is None and exp.start:
                            existing.start = exp.start
                        if existing.end is None and exp.end:
                            existing.end = exp.end
                        if existing.summary is None and exp.summary:
                            existing.summary = exp.summary
    return [seen[k] for k in order]


def _merge_location(records: list) -> Optional[LocationEntry]:
    """Pick location from highest-priority source that has one."""
    for src in ("csv", "ats", "github"):
        for rec in records:
            if rec.source == src and rec.location:
                return rec.location
    return None


def _merge_links(records: list) -> LinksEntry:
    links = LinksEntry()
    other_set = set()
    # Later sources fill in gaps
    for src in ("csv", "ats", "github"):
        for rec in records:
            if rec.source == src and rec.links:
                if rec.links.linkedin and not links.linkedin:
                    links.linkedin = rec.links.linkedin
                if rec.links.github and not links.github:
                    links.github = rec.links.github
                if rec.links.portfolio and not links.portfolio:
                    links.portfolio = rec.links.portfolio
                for o in rec.links.other:
                    other_set.add(o)
    links.other = sorted(other_set)
    return links


def _merge_provenance(records: list) -> list:
    seen = set()
    result = []
    for rec in records:
        for p in rec.provenance:
            key = (p.field, p.source, p.method)
            if key not in seen:
                seen.add(key)
                result.append(p)
    return result


def _make_candidate_id(emails: list, name: Optional[str]) -> str:
    import hashlib
    key = (emails[0] if emails else (name or "unknown")).lower()
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def merge_group(records: list) -> dict:
    """Collapse a group of CandidateRecords into one canonical output dict."""
    emails = _merge_emails(records)
    phones = _merge_phones(records)
    skills = _merge_skills(records)
    experience = _merge_experience(records)
    location = _merge_location(records)
    links = _merge_links(records)
    provenance = _merge_provenance(records)

    full_name, _ = _pick_scalar("full_name", records)
    headline_val, _ = _pick_scalar("headline", records)
    years_exp, _ = _pick_scalar("years_experience", records)

    # For headline: union from all sources (bio + title blend)
    headlines = []
    for src in ("csv", "ats", "github"):
        for rec in records:
            if rec.source == src and rec.headline and rec.headline not in headlines:
                headlines.append(rec.headline)
    # Use first as primary; if multiple differ, prefer the most descriptive (longest)
    if headlines:
        headline_val = max(headlines, key=len)
    else:
        headline_val = None

    candidate_id = _make_candidate_id(emails, full_name)

    return {
        "candidate_id": candidate_id,
        "full_name": full_name,
        "emails": emails,
        "phones": phones,
        "location": {
            "city": location.city if location else None,
            "region": location.region if location else None,
            "country": location.country if location else None,
        },
        "links": {
            "linkedin": links.linkedin,
            "github": links.github,
            "portfolio": links.portfolio,
            "other": links.other,
        },
        "headline": headline_val,
        "years_experience": years_exp,
        "skills": [
            {"name": s.name, "confidence": s.confidence, "sources": sorted(s.sources)}
            for s in skills
        ],
        "experience": [
            {
                "company": e.company,
                "title": e.title,
                "start": e.start,
                "end": e.end,
                "summary": e.summary,
            }
            for e in experience
        ],
        "education": [
            {
                "institution": e.institution,
                "degree": e.degree,
                "field": e.field,
                "end_year": e.end_year,
            }
            for e in (
                edu for rec in records for edu in rec.education
            )
        ],
        "provenance": [
            {"field": p.field, "source": p.source, "method": p.method}
            for p in provenance
        ],
        "overall_confidence": 0.0,  # filled by confidence stage
        "_source_records": records,  # internal — stripped before output
    }


def merge_all(records: list) -> list:
    """Group records and merge each group. Returns list of merged dicts."""
    groups = _group_records(records)
    return [merge_group(grp) for grp in groups]
