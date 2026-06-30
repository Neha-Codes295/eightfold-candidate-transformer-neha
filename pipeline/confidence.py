"""
Confidence scoring:
  per-field confidence = (sources agreeing on value) / (sources providing field)
  overall confidence   = average of per-field confidences
"""
from models.candidate import CandidateRecord

# Fields we score confidence for (scalar and list fields)
SCORED_FIELDS = [
    "full_name", "emails", "phones", "headline",
    "years_experience", "skills", "experience", "location",
]


def _sources_providing(field: str, records: list) -> list:
    """Return list of source names that provided a non-empty value for field."""
    sources = []
    for rec in records:
        val = getattr(rec, field, None)
        if val is not None and val != [] and val != "":
            sources.append(rec.source)
    return sources


def _sources_agreeing(field: str, records: list) -> int:
    """
    Count how many sources agree on the same value for this field.
    For lists (emails, phones, skills): check overlap rather than exact equality.
    Returns count of agreeing sources.
    """
    values_by_source: dict[str, object] = {}
    for rec in records:
        val = getattr(rec, field, None)
        if val is not None and val != [] and val != "":
            values_by_source[rec.source] = val

    if len(values_by_source) <= 1:
        return len(values_by_source)  # 1 source = confidence 1.0 by definition

    sources = list(values_by_source.keys())
    agree_count = 1  # first source always "agrees with itself"

    first_val = values_by_source[sources[0]]

    for src in sources[1:]:
        val = values_by_source[src]
        if isinstance(first_val, list) and isinstance(val, list):
            # Check for any overlap (e.g., shared emails/skills)
            if set(str(v).lower() for v in first_val) & set(str(v).lower() for v in val):
                agree_count += 1
        elif isinstance(first_val, str) and isinstance(val, str):
            if first_val.lower().strip() == val.lower().strip():
                agree_count += 1
        elif first_val == val:
            agree_count += 1

    return agree_count


def compute_confidence(merged: dict) -> dict:
    """
    Compute per-field and overall confidence.
    Mutates merged dict in place (adds per-skill confidence, overall_confidence).
    Returns the dict.
    """
    records: list[CandidateRecord] = merged.get("_source_records", [])
    if not records:
        merged["overall_confidence"] = 0.0
        return merged

    per_field_confidences = []

    for field in SCORED_FIELDS:
        providing = _sources_providing(field, records)
        n_providing = len(providing)
        if n_providing == 0:
            continue
        n_agreeing = _sources_agreeing(field, records)
        conf = n_agreeing / n_providing
        per_field_confidences.append(conf)

    # Per-skill confidence: fraction of providing sources that include that skill
    all_source_names = {rec.source for rec in records}
    skill_source_sets: dict[str, set] = {}
    for rec in records:
        for skill in rec.skills:
            key = skill.name.lower().strip()
            skill_source_sets.setdefault(key, set()).add(rec.source)

    # Sources that provided ANY skills
    sources_with_skills = {rec.source for rec in records if rec.skills}
    n_skill_sources = len(sources_with_skills)

    updated_skills = []
    for skill_dict in merged.get("skills", []):
        name = skill_dict["name"]
        skill_sources = skill_source_sets.get(name, set())
        conf = len(skill_sources) / n_skill_sources if n_skill_sources > 0 else 1.0
        updated_skills.append({
            "name": name,
            "confidence": round(conf, 4),
            "sources": sorted(skill_sources),
        })

    merged["skills"] = sorted(updated_skills, key=lambda s: (-s["confidence"], s["name"]))

    overall = sum(per_field_confidences) / len(per_field_confidences) if per_field_confidences else 0.0
    merged["overall_confidence"] = round(overall, 4)
    return merged
