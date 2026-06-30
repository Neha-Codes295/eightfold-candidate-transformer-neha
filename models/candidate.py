"""
Canonical intermediate representation used between pipeline stages.
All extract functions return a CandidateRecord; all pipeline stages operate on it.
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ProvenanceEntry:
    field: str
    source: str   # "csv" | "ats" | "github"
    method: str   # "direct" | "mapped" | "api" | "inferred"


@dataclass
class SkillEntry:
    name: str
    confidence: float = 1.0
    sources: list = field(default_factory=list)


@dataclass
class ExperienceEntry:
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None    # YYYY-MM
    end: Optional[str] = None      # YYYY-MM or None = present
    summary: Optional[str] = None


@dataclass
class EducationEntry:
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


@dataclass
class LocationEntry:
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None  # ISO-3166 alpha-2


@dataclass
class LinksEntry:
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list = field(default_factory=list)


@dataclass
class CandidateRecord:
    """Intermediate canonical record produced by extract and consumed by merge."""
    source: str                          # which source produced this record
    candidate_id: Optional[str] = None
    full_name: Optional[str] = None
    emails: list = field(default_factory=list)
    phones: list = field(default_factory=list)
    location: Optional[LocationEntry] = None
    links: Optional[LinksEntry] = None
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list = field(default_factory=list)   # list[SkillEntry]
    experience: list = field(default_factory=list)  # list[ExperienceEntry]
    education: list = field(default_factory=list)   # list[EducationEntry]
    provenance: list = field(default_factory=list)  # list[ProvenanceEntry]
    raw: Any = None                       # original raw data, for debugging


def empty_canonical() -> dict:
    """Return the default output schema shape with all nulls."""
    return {
        "candidate_id": None,
        "full_name": None,
        "emails": [],
        "phones": [],
        "location": {"city": None, "region": None, "country": None},
        "links": {"linkedin": None, "github": None, "portfolio": None, "other": []},
        "headline": None,
        "years_experience": None,
        "skills": [],
        "experience": [],
        "education": [],
        "provenance": [],
        "overall_confidence": 0.0,
    }
